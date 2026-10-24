#!/usr/bin/python3
"""One boot, one attempt. No recovery writes. Runtime requires a future boot."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
import uuid

MODULES = ('nvidia', 'nvidia_uvm', 'nvidia_modeset', 'nvidia_drm', 'snd_hda_intel')
FLAGS = tuple(k + '=' + ','.join(MODULES) for k in ('rd.driver.blacklist', 'modprobe.blacklist'))
BLOCKED_BOOT = 'd05627f7-8703-40d8-bc36-971578675050'
ROUTER_UUID = 'ba7e8780-0065-ebf9-ffff-ffffffffffff'
GPU = (0x10de, 0x2d04, 0x030000, 0x1043, 0x8a11)
BRIDGE = (0x8086, 0x5786, 0x060400, 0x2222, 0x1111)
AUDIO = (0x10de, 0x22eb, 0x040300, 0x10de, 0x0000)  # Actual RTX HDA function subsystem
FIELDS = ('vendor', 'device', 'class', 'subsystem_vendor', 'subsystem_device')

class Stop(RuntimeError):
    pass

def require(ok, message):
    if not ok:
        raise Stop(message)

def read(path):
    return path.read_text().strip()

def secure(path, mode, owner=0):
    s = path.lstat()
    require(s.st_uid == owner and s.st_gid == owner and stat.S_IMODE(s.st_mode) == mode
            and not stat.S_ISLNK(s.st_mode), 'unsafe ownership/mode: ' + str(path))
    return s

def directory(path, owner=0):
    # Reject symlink and writable ancestors before any creation.
    for p in reversed((path, *path.parents)):
        if p.exists() or p.is_symlink():
            s = p.lstat()
            require(stat.S_ISDIR(s.st_mode) and s.st_uid == owner and not s.st_mode & 0o022,
                    'unsafe directory: ' + str(p))
        else:
            p.mkdir(mode=0o700)
    secure(path, 0o700, owner)

def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def atomic(path, data, mode=0o600):
    tmp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            if os.geteuid() == 0:
                os.fchown(f.fileno(), 0, 0)
            os.fchmod(f.fileno(), mode)
            os.fsync(f.fileno())
        os.replace(tmp, path)
        fsync_dir(path.parent)
    finally:
        tmp.unlink(missing_ok=True)

class Boot:
    def __init__(self, root=Path('/'), command=None, uid=os.geteuid,
                 clock=time.monotonic, sleep=time.sleep, sync=os.fsync, owner=0):
        self.root, self.uid, self.owner = Path(root), uid, owner
        self.clock, self.sleep, self.sync = clock, sleep, sync
        self.command = command or self.run
        self.fd = None
        self.deadline = None
        self._kernel_last_t = None  # bound journalctl work during boot/hotplug wait
        self.state = self.root / 'var/lib/ai-egpu-gen3-ha'
        self.runtime = self.root / 'run/ai-egpu-gen3-ha'
        self.marker = self.runtime / 'ready.json'
        self.pci = self.root / 'sys/bus/pci/devices'

    def run(self, args):
        timeout = min(5, self.deadline - self.clock()) if self.deadline else 5
        require(timeout > 0, 'deadline exceeded')
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'})
        require(p.returncode == 0, 'command failed: ' + args[0] + ': ' + p.stderr[-500:])
        return p.stdout.strip()

    def boot_id(self):
        boot = str(uuid.UUID(read(self.root / 'proc/sys/kernel/random/boot_id')))
        require(boot != BLOCKED_BOOT, 'current driver-used boot forbidden')
        return boot

    def guard(self, unbound, force_journal=False):
        require(self.boot_id() == self.boot, 'boot changed')
        tokens = read(self.root / 'proc/cmdline').split()
        require(all(f in tokens for f in FLAGS), 'missing kernel blacklist')
        modules = {s.split()[0] for s in read(self.root / 'proc/modules').splitlines() if s}
        modules |= {p.name for p in (self.root / 'sys/module').iterdir()}
        require('snd_hda_intel' not in modules, 'audio module present')
        if unbound:
            require(not any(m.startswith('nvidia') for m in modules), 'NVIDIA module present')
        # journalctl is expensive during init. Never run it dozens of times per
        # second in the PCI polling loop. Recheck fresh before EVERY hardware
        # write, once after retrain and after driver binding.
        if (force_journal or self._kernel_last_t is None or
                self.clock() - self._kernel_last_t >= 2.0):
            log = self.command(['/usr/bin/journalctl', '-k', '-b', '--no-pager', '-o', 'cat'])
            require(log and '-- No entries --' not in log, 'kernel journal unavailable')
            require(not re.search(r'\bNVRM:\s*Xid\b|\bAER:.*(?:error|received)|PCIe Bus Error', log, re.I),
                    'Xid/AER in boot journal')
            if unbound:
                lines = '\n'.join(x for x in log.splitlines()
                                  if not re.match(r'^(?:Kernel )?Command line:', x))
                require(not re.search(r'\bNVRM:|\bnvidia(?:[-_][a-z0-9_]+)?\s*(?::|\[|0000:)|\bsnd_hda_intel\s+0000:', lines, re.I),
                        'driver history in boot')
            self._kernel_last_t = self.clock()

    def identity(self, p):
        return tuple(int(read(p / f), 16) for f in FIELDS)

    def discover(self, unbound):
        devices = list(self.pci.iterdir())
        gpus = [p for p in devices if int(read(p / 'vendor'), 16) == 0x10de
                and int(read(p / 'class'), 16) >> 16 == 3]
        require(len(gpus) == 1, 'missing/ambiguous GPU')
        gpu = gpus[0]
        require(self.identity(gpu) == GPU and gpu.name.endswith('.0'), 'wrong GPU/subsys')
        bridge = self.pci / gpu.resolve().parent.name
        require(bridge.exists() and self.identity(bridge) == BRIDGE, 'wrong bridge/subsys')
        require(gpu.resolve().parent == bridge.resolve(), 'wrong direct parent')
        audio = self.pci / (gpu.name[:-1] + '1')
        require(audio.exists() and self.identity(audio) == AUDIO, 'wrong audio/subsys')
        require(audio.resolve().parent == bridge.resolve(), 'wrong audio parent')
        require({p.name for p in devices if p.resolve().parent == bridge.resolve()} == {gpu.name, audio.name},
                'unexpected downstream devices')
        # PCIe bridges are normally managed by kernel pcieport. Never detach it.
        if os.path.lexists(bridge / 'driver'):
            require((bridge / 'driver').resolve().name == 'pcieport', 'unexpected bridge driver')
        for p in (audio,) + ((gpu,) if unbound else ()):
            require(not os.path.lexists(p / 'driver'), 'driver bound: ' + p.name)
        if not unbound and os.path.lexists(gpu / 'driver'):
            require((gpu / 'driver').resolve().name == 'nvidia', 'wrong GPU driver')
        routers = [p for p in (self.root / 'sys/bus/thunderbolt/devices').iterdir()
                   if (p / 'device_name').exists()]
        require(len(routers) == 1, 'missing/ambiguous USB4 router')
        router = routers[0]
        require(read(router / 'device_name') == 'TBGAA' and read(router / 'unique_id') == ROUTER_UUID,
                'wrong TBGAA/UUID')
        require(read(router / 'authorized') == '1', 'USB4 unauthorized')
        for direction in ('rx', 'tx'):
            require(read(router / (direction + '_speed')) == '20.0 Gb/s'
                    and read(router / (direction + '_lanes')) == '2', 'USB4 not 40Gb/s')
        paths = [gpu, bridge, audio, router]
        # Inode + resolved path detects same-BDF remove/re-add during this boot.
        topology = [{'path': str(p.resolve().relative_to(self.root)), 'inode': p.stat().st_ino}
                    for p in paths]
        for p in (gpu, bridge):
            for f in p.glob('aer_dev_*'):
                numbers = re.findall(r'\b\d+\b', read(f))
                require(numbers and all(int(n) == 0 for n in numbers), 'nonzero AER counter')
        return gpu, bridge, topology

    def snapshot(self, unbound=True, force_journal=False):
        self.guard(unbound, force_journal=force_journal)
        return self.discover(unbound)

    def reg(self, dev, expr):
        result = self.command(['/usr/bin/setpci', '-s', dev.name, expr])
        size = 8 if expr.endswith('.l') else 2 if expr.endswith('.b') else 4
        require(re.fullmatch('[0-9a-fA-F]{%d}' % size, result) and result.lower() != 'f' * size,
                'invalid config read')
        return int(result, 16)

    def registers(self, dev, gpu, transient=False):
        ident = GPU if gpu else BRIDGE
        require(self.reg(dev, '00.l') == ident[1] << 16 | ident[0], 'config identity')
        require(self.reg(dev, '06.w') & 16, 'missing capability list')
        offset, seen, express = self.reg(dev, '34.b'), set(), []
        while offset:
            require(0x40 <= offset <= 0xfc and offset % 4 == 0 and offset not in seen, 'capability chain')
            seen.add(offset)
            header = self.reg(dev, f'{offset:02x}.w')
            if header & 255 == 16:
                express.append(offset)
            offset = header >> 8
        require(express == [0x60 if gpu else 0xc0], 'wrong PCIe capability offset')
        require(self.reg(dev, 'CAP_EXP+02.w') == (0x12 if gpu else 0x162), 'wrong PCIe version/type')
        dsta = self.reg(dev, 'CAP_EXP+0a.w')
        errors = dsta & 0x000f
        # Device Status bits 0-3 are RW1C: an error detected during firmware
        # / PCI enumeration can remain latched. On this exact RTX 5060 Ti the
        # observed cold-boot value is 0009 (CED|URD), with all AER counters 0.
        # Only this exact historic pattern or clean 0000 is tolerated on GPU.
        # NFED/FED and any other pattern still fail closed. No status clearing.
        require(errors in ((0, 0x0009) if gpu else (0,)),
                'unexpected PCIe Device Status flags: %04x' % dsta)
        vector = self.reg(dev, 'CAP_EXP+2c.l')
        require(vector & 8, 'unsupported Gen3')
        ctl, ctl2, sta = [self.reg(dev, r) for r in ('CAP_EXP+10.w', 'CAP_EXP+30.w', 'CAP_EXP+12.w')]
        require(not ctl & 16, 'link disabled')
        require(1 <= ctl2 & 15 <= 6 and vector & (1 << (ctl2 & 15)), 'invalid target speed')
        require((sta >> 4) & 63 == 4 and 1 <= sta & 15 <= 6 and vector & (1 << (sta & 15)), 'invalid speed/width')
        if not transient:
            require(not ctl & 32 and not sta & 0x800, 'link training')
            speed = {1:'2.5', 2:'5.0', 3:'8.0', 4:'16.0', 5:'32.0', 6:'64.0'}[sta & 15]
            require(read(dev / 'current_link_width') == '4' and
                    read(dev / 'current_link_speed') == speed + ' GT/s PCIe', 'sysfs link mismatch')
        return {'ctl': ctl, 'ctl2': ctl2, 'sta': sta, 'devsta': dsta}

    def event(self, event, **data):
        payload = (json.dumps(dict(event=event, **data), sort_keys=True) + '\n').encode()
        while payload:
            n = os.write(self.fd, payload)
            require(n > 0, 'journal short write')
            payload = payload[n:]
        self.sync(self.fd)

    def full(self, baseline, expected=None, unbound=True, transient=False, force_journal=False):
        gpu, bridge, topology = self.snapshot(unbound, force_journal=force_journal)
        require(topology == baseline, 'topology/hotplug changed')
        regs = [self.registers(gpu, True, transient), self.registers(bridge, False, transient)]
        if not transient:
            require(regs[0]['sta'] & 15 == regs[1]['sta'] & 15, 'link ends disagree')
        if expected is not None:
            for actual, want in zip(regs, expected):
                require(actual['ctl2'] == want['ctl2'] and actual['ctl'] & ~32 == want['ctl'] & ~32,
                        'link control drift')
                # Cleared historic flags are fine. A newly asserted bit outside
                # the recorded baseline is not. Existing RW1C flags cannot
                # detect recurrence of the same bit; document this limitation.
                require(not ((actual['devsta'] & 0x000f) & ~(want['devsta'] & 0x000f)),
                        'new PCIe Device Status flag detected')
        return regs

    def verify_ready(self):
        require(self.uid() == 0, 'root required')
        self.boot = self.boot_id()
        secure(self.runtime, 0o700, self.owner)
        secure(self.marker, 0o600, self.owner)
        fd = os.open(self.marker, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as f:
            s = os.fstat(f.fileno())
            require(s.st_uid == self.owner and s.st_gid == self.owner and stat.S_IMODE(s.st_mode) == 0o600
                    and stat.S_ISREG(s.st_mode), 'unsafe marker')
            marker = json.load(f)
        require(marker['boot_id'] == self.boot, 'stale boot marker')
        regs = self.full(marker['topology'], marker['registers'], unbound=False,
                         force_journal=True)
        require(all(r['ctl2'] & 0x2f == 0x23 and r['sta'] & 15 == 3 for r in regs), 'not Gen3+HA')
        return marker

    def load(self, module):
        require(module in MODULES[:4], 'module not allowed')
        self.verify_ready()
        self.command(['/usr/sbin/modprobe', '--ignore-install', module])
        self.verify_ready()

    def previous_boot_gate(self):
        # A crash before the terminal PASS must not cause an unattended reboot
        # loop on a headless host. Failed/incomplete attempts need manual review.
        previous = sorted(
            (p for p in self.state.glob('attempt-*.jsonl')
             if p.name != 'attempt-' + self.boot + '.jsonl'),
            key=lambda p: p.stat().st_mtime_ns)
        if not previous:
            return
        last = previous[-1]
        secure(last, 0o600, self.owner)
        try:
            rows = [json.loads(line) for line in last.read_text().splitlines()]
        except (OSError, ValueError, TypeError) as exc:
            raise Stop('prior boot journal corrupt: ' + str(exc)) from exc
        require(rows and rows[-1].get('event') == 'PASS',
                'prior boot GPU attempt incomplete/failed: manual recovery required')

    def apply(self):
        own_marker = False
        try:
            require(self.uid() == 0, 'root required')
            self.boot = self.boot_id()
            directory(self.state, self.owner)
            directory(self.runtime, self.owner)
            own_marker = True
            require(not os.path.lexists(self.marker), 'ready marker already exists')
            self.previous_boot_gate()  # stop unattended reboot loops after failed boot
            # Reserve before discovery; failure/timeout is also a consumed attempt.
            path = self.state / ('attempt-' + self.boot + '.jsonl')
            self.fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            if os.geteuid() == 0:
                os.fchown(self.fd, 0, 0)
            self.sync(self.fd)
            fsync_dir(self.state)
            self.event('attempt', boot_id=self.boot)
            self.deadline = self.clock() + 50
            self._kernel_last_t = None  # no cache may survive a boot-ID transition
            previous, stable_since = None, None
            last_discovery_error = 'no stable sample'
            # Reserve two seconds for a clean, informative timeout instead of
            # accidentally passing a 0.007s deadline to journalctl.
            while self.clock() + 2.0 < self.deadline:
                self.guard(True)  # Driver history/module violations never get retried.
                try:
                    gpu, bridge, topology = self.discover(True)
                    regs = self.full(topology)
                    sample = (topology, regs)
                    if sample == previous:
                        if self.clock() - stable_since >= 1:
                            break
                    else:
                        previous, stable_since = sample, self.clock()
                except (Stop, OSError, ValueError) as exc:
                    last_discovery_error = str(exc)
                    previous, stable_since = None, None
                self.sleep(min(0.2, max(0, self.deadline - self.clock())))
            else:
                raise Stop('discovery/stabilization timeout: ' + last_discovery_error)
            self.deadline = self.clock() + 10
            expected = [dict(r) for r in regs]
            self.event('original', topology=topology, registers=regs,
                       pci_device_status=[r['devsta'] for r in regs],
                       cold_boot_latched_status=(regs[0]['devsta'] & 15) == 9)
            operations = [(0, 'CAP_EXP+30.w', 3, 15), (1, 'CAP_EXP+30.w', 3, 15),
                          (0, 'CAP_EXP+30.w', 32, 32), (1, 'CAP_EXP+30.w', 32, 32),
                          (1, 'CAP_EXP+10.w', 32, 32)]
            for index, reg, value, mask in operations:
                dev = (gpu, bridge)[index]
                self.full(topology, expected)
                key = 'ctl2' if reg == 'CAP_EXP+30.w' else 'ctl'
                before = expected[index][key]
                self.event('write-intent', bdf=dev.name, register=reg, value=value, mask=mask, before=before)
                # Fresh kernel check immediately before the irreversible write.
                self.full(topology, expected, force_journal=True)
                require(self.reg(dev, reg) == before, 'register changed after intent')
                retrain = key == 'ctl'
                if retrain:
                    self.deadline = self.clock() + 3
                self.command(['/usr/bin/setpci', '-s', dev.name, f'{reg}={value:04x}:{mask:04x}'])
                actual = self.reg(dev, reg)
                wanted = (before & ~mask) | value
                require(actual & ~32 == before & ~32 if retrain else actual == wanted, 'write readback mismatch')
                if not retrain:
                    expected[index][key] = wanted
                self.full(topology, expected, transient=retrain)
                self.event('write-readback', actual=actual)
            while self.clock() < self.deadline:
                regs = self.full(topology, expected, transient=True)
                if all(r['sta'] & 15 == 3 and not r['sta'] & 0x800 and not r['ctl'] & 32 for r in regs):
                    regs = self.full(topology, expected)
                    require(self.clock() < self.deadline, 'poll timeout')
                    break
                self.sleep(min(0.05, max(0, self.deadline - self.clock())))
            else:
                raise Stop('poll timeout')
            self.event('link-PASS', registers=regs)
            require(self.clock() < self.deadline, 'poll timeout')
            self.deadline = self.clock() + 8
            self.full(topology, expected, force_journal=True)
            marker = dict(boot_id=self.boot, topology=topology, registers=regs)
            own_marker = True
            atomic(self.marker, json.dumps(marker).encode())
            self.load('nvidia')
            require((gpu / 'driver').resolve().name == 'nvidia' and (gpu / 'driver').exists(), 'NVIDIA not bound')
            self.verify_ready()
            self.event('PASS')
            return {'status': 'PASS', 'boot_id': self.boot}
        except (Stop, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            if own_marker:
                self.marker.unlink(missing_ok=True)
                fsync_dir(self.runtime)
            if self.fd is not None:
                try:
                    self.event('FAIL', reason=str(exc))
                except (Stop, OSError):
                    pass
            return {'status': 'FAIL', 'reason': str(exc)}
        finally:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            self.deadline = None

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['apply', 'verify-ready', 'status'])
    args = parser.parse_args()
    b = Boot()
    try:
        if args.action == 'apply':
            result = b.apply()
        elif args.action == 'status':
            # No PCI access, even on the protected current boot.
            result = {'status': 'INFO', 'marker_exists': b.marker.exists(),
                      'attempts': sorted(p.name for p in b.state.glob('attempt-*.jsonl'))}
        else:
            result = {'status': 'PASS', 'ready': b.verify_ready()}
    except (Stop, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        result = {'status': 'FAIL', 'reason': str(exc)}
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] in ('PASS', 'INFO') else 1

if __name__ == '__main__':
    raise SystemExit(main())
