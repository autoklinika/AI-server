#!/usr/bin/env python3
"""Single-use CUDA PTX compute: small verification, short load, long load.
No PCIe writes, no services, no NVML, no GPU automatic retry.
"""
import argparse
from array import array
import ctypes as ct
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

BOOT = "d05627f7-8703-40d8-bc36-971578675050"
ROUTER = "ba7e8780-0065-ebf9-ffff-ffffffffffff"
ROOT = Path("/srv/ai-data/staging/egpu-gen3-ha-compute-20261023")
GPU = Path("/sys/bus/pci/devices/0000:03:00.0")
BRIDGE = Path("/sys/bus/pci/devices/0000:02:00.0")
STAGES = {"small": (65536, 8, 0),
          "short": (262144, 256, 10),
          "long": (1048576, 512, 40)}
M32 = 0xffffffff

PTX = b""".version 7.0
.target sm_80
.address_size 64

.visible .entry lcg_add(
 .param .u64 a_ptr,
 .param .u64 b_ptr,
 .param .u64 o_ptr,
 .param .u32 count,
 .param .u32 niter
)
{
 .reg .pred %p;
 .reg .b32 %r<12>;
 .reg .b64 %rd<8>;
 ld.param.u64 %rd1, [a_ptr];
 ld.param.u64 %rd2, [b_ptr];
 ld.param.u64 %rd3, [o_ptr];
 ld.param.u32 %r5, [count];
 ld.param.u32 %r10, [niter];
 mov.u32 %r1, %ctaid.x;
 mov.u32 %r2, %ntid.x;
 mov.u32 %r3, %tid.x;
 mad.lo.u32 %r4, %r1, %r2, %r3;
 setp.ge.u32 %p, %r4, %r5;
 @%p bra EXIT;
 mul.wide.u32 %rd4, %r4, 4;
 add.u64 %rd5, %rd1, %rd4;
 add.u64 %rd6, %rd2, %rd4;
 add.u64 %rd7, %rd3, %rd4;
 ld.global.u32 %r6, [%rd5];
 ld.global.u32 %r7, [%rd6];
 add.u32 %r8, %r6, %r7;
 mov.u32 %r9, 0;
LOOP:
 setp.ge.u32 %p, %r9, %r10;
 @%p bra STORE;
 mad.lo.u32 %r8, %r8, 1664525, 1013904223;
 add.u32 %r9, %r9, 1;
 bra LOOP;
STORE:
 st.global.u32 [%rd7], %r8;
EXIT:
 ret;
}
"""


def read(path):
    return Path(path).read_text().strip()


def check(ok, msg):
    if not ok:
        raise RuntimeError(msg)


def preflight():
    check(read("/proc/sys/kernel/random/boot_id") == BOOT, "wrong boot")
    check(GPU.is_dir() and BRIDGE.is_dir(), "GPU/bridge missing")
    check(read(GPU / "vendor") == "0x10de" and
          read(GPU / "device") == "0x2d04", "wrong GPU")
    check(read(BRIDGE / "vendor") == "0x8086" and
          read(BRIDGE / "device") == "0x5786", "wrong bridge")
    check(GPU.resolve().parent == BRIDGE.resolve(), "unexpected topology")
    check((GPU / "driver").is_symlink() and
          (GPU / "driver").resolve().name == "nvidia", "NVIDIA not bound")
    router = Path("/sys/bus/thunderbolt/devices/0-2")
    check(router.is_dir() and read(router / "device_name") == "TBGAA" and
          read(router / "unique_id") == ROUTER and
          read(router / "authorized") == "1", "USB4 router mismatch")
    for p in (GPU, BRIDGE):
        check(read(p / "current_link_speed") == "8.0 GT/s PCIe" and
              read(p / "current_link_width") == "4", "not Gen3 x4")
        for f in ("aer_dev_correctable", "aer_dev_nonfatal", "aer_dev_fatal"):
            totals = [int(l.split()[-1]) for l in read(p / f).splitlines()
                      if l.startswith("TOTAL_")]
            check(len(totals) > 0 and not any(totals), "PCIe AER nonzero")
    for unit in ("ollama", "comfyui", "ai-gateway", "ai-platform-radio",
                 "nvidia-persistenced"):
        p = subprocess.run(["systemctl", "is-active", unit],
                           capture_output=True, text=True, timeout=3)
        check(p.stdout.strip() == "inactive", "GPU service active: " + unit)
    p = subprocess.run(["journalctl", "-k", "-b", "0", "--no-pager"],
                       capture_output=True, text=True, timeout=5)
    check(p.returncode == 0 and "NVRM: Xid" not in p.stdout and
          "GPU has fallen off the bus" not in p.stdout, "kernel GPU error")


class Journal:
    def __init__(self, mode):
        self.path = ROOT / ("once-" + BOOT + "-" + mode + ".jsonl")
        fd = os.open(self.path, os.O_CREAT | os.O_WRONLY |
                     os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self.fd = fd
        df = os.open(ROOT, os.O_DIRECTORY | os.O_RDONLY)
        try:
            os.fsync(fd)
            os.fsync(df)
        finally:
            os.close(df)
        self.write("START", mode=mode,
                   ptx_sha256=hashlib.sha256(PTX).hexdigest())

    def write(self, event, **kw):
        message = json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),
                                  boot_id=read("/proc/sys/kernel/random/boot_id"),
                                  event=event, **kw), sort_keys=True).encode() + b"\n"
        while message:
            n = os.write(self.fd, message)
            check(n > 0, "journal write failed")
            message = message[n:]
        os.fsync(self.fd)

    def close(self):
        os.close(self.fd)


class Cuda:
    def __init__(self, j):
        self.lib = ct.CDLL("libcuda.so.1")
        self.j = j

    def run(self, name, argtypes, *args):
        fn = getattr(self.lib, name)
        fn.argtypes, fn.restype = argtypes, ct.c_int
        self.j.write("CUDA_START", api=name)
        rc = fn(*args)
        self.j.write("CUDA_END", api=name, rc=rc)
        check(rc == 0, name + " CUDA_ERROR_" + str(rc))


def lcg(a, b, steps):
    v = (a + b) & M32
    for _ in range(steps):
        v = (v * 1664525 + 1013904223) & M32
    return v


def buffers(mode, count, steps):
    sz = count * 4
    if mode == "small":
        a = array("I", (((i * 2654435761) + 0x12345678) & M32
                        for i in range(count)))
        b = array("I", (((i * 2246822519) + 0x76543210) & M32
                        for i in range(count)))
        a_bytes, b_bytes = a.tobytes(), b.tobytes()
        expected = array("I", (lcg(x, y, steps) for x, y in zip(a, b))).tobytes()
    else:
        a_bytes, b_bytes = b"\xa5" * sz, b"\x5a" * sz
        expected = lcg(0xa5a5a5a5, 0x5a5a5a5a, steps).to_bytes(4, "little") * count
    check(len(expected) == sz, "expected bytes wrong")
    return (ct.create_string_buffer(a_bytes, sz),
            ct.create_string_buffer(b_bytes, sz),
            ct.create_string_buffer(sz), expected)


def execute(mode, j):
    check(sys.byteorder == "little" and array("I").itemsize == 4, "endianness")
    count, steps, seconds = STAGES[mode]
    preflight()
    a, b, out, expected = buffers(mode, count, steps)
    j.write("PREFLIGHT_PASS", count=count, steps=steps,
            seconds=seconds, bytes_per_buffer=count * 4)
    cuda = Cuda(j)
    P, U, S, D = ct.c_void_p, ct.c_uint, ct.c_size_t, ct.c_uint64
    ctx, mod, fn = P(), P(), P()
    ptrs = [D(), D(), D()]
    completed = False
    errors = []
    launches = 0
    try:
        cuda.run("cuInit", [U], 0)
        device = ct.c_int()
        cuda.run("cuDeviceGet", [ct.POINTER(ct.c_int), ct.c_int],
                 ct.byref(device), 0)
        cuda.run("cuCtxCreate_v2", [ct.POINTER(P), U, ct.c_int],
                 ct.byref(ctx), 0, device)
        ptx_buffer = ct.create_string_buffer(PTX)
        cuda.run("cuModuleLoadData", [ct.POINTER(P), P],
                 ct.byref(mod), ct.cast(ptx_buffer, P))
        cuda.run("cuModuleGetFunction", [ct.POINTER(P), P, ct.c_char_p],
                 ct.byref(fn), mod, b"lcg_add")
        for ptr in ptrs:
            cuda.run("cuMemAlloc_v2", [ct.POINTER(D), S],
                     ct.byref(ptr), count * 4)
        for src, dest in ((a, ptrs[0]), (b, ptrs[1])):
            cuda.run("cuMemcpyHtoD_v2", [D, P, S],
                     dest, ct.cast(src, P), count * 4)
        kernel_args = (D(ptrs[0].value), D(ptrs[1].value),
                       D(ptrs[2].value), U(count), U(steps))
        params = (P * len(kernel_args))(
            *(ct.cast(ct.byref(v), P) for v in kernel_args))

        def launch():
            cuda.run("cuLaunchKernel",
                     [P, U, U, U, U, U, U, U, P, ct.POINTER(P), P],
                     fn, (count + 255) // 256, 1, 1, 256, 1, 1, 0,
                     None, params, None)
            cuda.run("cuCtxSynchronize", [])

        start = time.monotonic()
        last_check = start
        while True:
            check(read("/proc/sys/kernel/random/boot_id") == BOOT, "boot changed")
            launch()
            launches += 1
            now = time.monotonic()
            if mode == "small" or now - last_check >= 5 or now - start >= seconds:
                cuda.run("cuMemcpyDtoH_v2", [P, D, S],
                         ct.cast(out, P), ptrs[2], count * 4)
                data = ct.string_at(out, count * 4)
                check(data == expected, "GPU result mismatch")
                check(read(GPU / "current_link_speed") == "8.0 GT/s PCIe" and
                      read(BRIDGE / "current_link_speed") == "8.0 GT/s PCIe",
                      "PCIe Gen3 lost under load")
                j.write("CHECKPOINT_PASS", launches=launches,
                        elapsed_s=round(now - start, 3),
                        verified_bytes=len(data),
                        sha256=hashlib.sha256(data).hexdigest())
                last_check = now
            if mode == "small" or now - start >= seconds:
                break
        j.write("COMPUTE_PASS", launches=launches,
                elapsed_s=round(time.monotonic() - start, 3))
        completed = True
    finally:
        for ptr in ptrs:
            if ptr.value:
                try:
                    cuda.run("cuMemFree_v2", [D], ptr)
                except Exception as e:
                    errors.append(str(e))
        if mod.value:
            try:
                cuda.run("cuModuleUnload", [P], mod)
            except Exception as e:
                errors.append(str(e))
        if ctx.value:
            try:
                cuda.run("cuCtxDestroy_v2", [P], ctx)
            except Exception as e:
                errors.append(str(e))
        if errors:
            j.write("CLEANUP_ERROR", errors=errors)
    check(completed and not errors, "compute/cleanup failed")
    preflight()
    j.write("STAGE_PASS", mode=mode, launches=launches)
    return launches


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=tuple(STAGES))
    ap.add_argument("--allow-disruptive", action="store_true")
    args = ap.parse_args()
    check(args.allow_disruptive, "explicit --allow-disruptive required")
    preflight()
    j = Journal(args.mode)
    try:
        launches = execute(args.mode, j)
        print(json.dumps(dict(status="PASS", mode=args.mode, launches=launches,
                              journal=str(j.path))), flush=True)
    except Exception as exc:
        j.write("STOP", reason=str(exc))
        print(json.dumps(dict(status="STOP", mode=args.mode, reason=str(exc),
                              journal=str(j.path))), flush=True)
        raise SystemExit(2)
    finally:
        j.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps(dict(status="STOP", reason=str(exc))), flush=True)
        raise SystemExit(2)
