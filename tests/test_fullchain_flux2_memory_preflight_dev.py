"""CPU metadata-only FLUX memory preflight: valid, forged and insufficient cases."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import struct
import sys

import pytest

SOURCE = (Path(__file__).resolve().parents[1]
          / "tools/local_image/fullchain_flux2_memory_preflight_dev.py")
spec = importlib.util.spec_from_file_location("fullchain_memory_metadata_contract", SOURCE)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def fake_safetensors(path: Path, specs=None, raw=b"\x00" * 16):
    specs = specs or {
        "weights": {"dtype": "BF16", "shape": [2, 4], "data_offsets": [0, 16]}
    }
    header = json.dumps(specs).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(header)) + header + raw)
    return path


def test_reads_only_header_and_correct_weight_lower_bound(tmp_path):
    file = fake_safetensors(tmp_path / "model.safetensors")
    summary = m.inspect_weights(file)
    assert summary["tensors"] == 1
    assert summary["weight_payload_bytes"] == 16
    assert summary["dtype_bytes"] == {"BF16": 16}


@pytest.mark.parametrize("metadata", [
    {"x": {"dtype": "WRONG", "shape": [2, 4], "data_offsets": [0, 16]}},
    {"x": {"dtype": "BF16", "shape": [-1, 4], "data_offsets": [0, 16]}},
    {"x": {"dtype": "BF16", "shape": [2, 4], "data_offsets": [0, 15]}},
    {"x": {"dtype": "BF16", "shape": [2, 4], "data_offsets": [0, 17]}},
    {"x": {"dtype": "BF16", "shape": [2, 4], "data_offsets": [-1, 15]}},
])
def test_rejects_untrusted_tensor_shapes(tmp_path, metadata):
    file = fake_safetensors(tmp_path / "fake.safetensors", metadata)
    with pytest.raises(m.MemoryPreflightBlocked):
        m.inspect_weights(file)


def test_overlapping_tensor_ranges_refused(tmp_path):
    specs = {
        "a": {"dtype": "F32", "shape": [2], "data_offsets": [0, 8]},
        "b": {"dtype": "F32", "shape": [2], "data_offsets": [4, 12]},
    }
    with pytest.raises(m.MemoryPreflightBlocked, match="overlapping"):
        m.inspect_weights(fake_safetensors(tmp_path / "overlap.safetensors", specs))


def test_symlink_model_is_not_trusted(tmp_path):
    real = fake_safetensors(tmp_path / "real.safetensors")
    link = tmp_path / "link.safetensors"
    link.symlink_to(real)
    with pytest.raises(m.MemoryPreflightBlocked, match="symlink"):
        m.inspect_weights(link)


def test_huge_or_missing_header_refused(tmp_path):
    file = tmp_path / "invalid.safetensors"
    file.write_bytes(struct.pack("<Q", 1 << 40))
    with pytest.raises(m.MemoryPreflightBlocked, match="metadata length"):
        m.inspect_weights(file)


@pytest.mark.parametrize("raw", ["12G", "16G", "2M", "1K"])
def test_parses_exact_systemd_limits(raw):
    assert m.parse_limit(raw) == int(raw[:-1]) * 1024 ** (
        "KMGT".index(raw[-1]) + 1
    )


@pytest.mark.parametrize("raw", ["0G", "infinity", "12GB", "1.5G", "-1G", ""])
def test_rejects_unsafe_or_ambiguous_systemd_limits(raw):
    with pytest.raises(m.MemoryPreflightBlocked):
        m.parse_limit(raw)


def test_unit_memorymax_must_be_unique():
    with pytest.raises(m.MemoryPreflightBlocked):
        m.unit_limit("[Service]\nMemoryMax=12G\nMemoryMax=14G\n")
    assert m.unit_limit("[Service]\nMemoryMax=12G\n") == 12 * m.GIB


def test_host_physical_ram_validation(tmp_path):
    f = tmp_path / "meminfo"
    f.write_text("MemTotal: 31965708 kB\nMemAvailable: 25800000 kB\n")
    assert m.host_memory(f)["MemTotal"] == 31965708 * 1024
    f.write_text("MemTotal: 31965708 kB\nMemAvailable: 45000000 kB\n")
    with pytest.raises(m.MemoryPreflightBlocked):
        m.host_memory(f)


def test_full_weights_floor_blocks_tight_12g_cgroup():
    files = {
        "klein": {"weight_payload_bytes": int(3.791 * m.GIB)},
        "qwen_text": {"weight_payload_bytes": int(7.492 * m.GIB)},
        "vae": {"weight_payload_bytes": int(.313 * m.GIB)},
    }
    result = m.analyze(data=files, memory_max=12*m.GIB,
                       mem_total=30*m.GIB, mem_available=25*m.GIB)
    assert result["cgroup_screen"] == "INSUFFICIENT"
    assert result["host_screen"] == "PASS"
    assert result["gpu_memory_peak"] == "NOT_MEASURED"
    assert result["fullchain_gpu_authorized"] is False


def test_low_ram_also_blocks_even_with_higher_cgroup():
    files = {"weights": {"weight_payload_bytes": 12*m.GIB}}
    result = m.analyze(data=files, memory_max=20*m.GIB,
                       mem_total=20*m.GIB, mem_available=13*m.GIB)
    assert result["host_screen"] == "INSUFFICIENT"
    assert result["fullchain_gpu_authorized"] is False
