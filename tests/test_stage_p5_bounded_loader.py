"""CPU-only tests: python -m unittest discover -s tests -p test_stage_p5_bounded_loader.py."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

try:
    import torch
    from safetensors.torch import save_file
except ImportError:
    torch = None

LOADER = Path(__file__).resolve().parents[1] / "deploy/stage-p5/training/streaming_bf16_loader.py"
spec = importlib.util.spec_from_file_location("p5_loader", LOADER)
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)


@unittest.skipIf(torch is None, "CPU tensor tests require torch and safetensors")
class StreamingLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def checkpoint(self, state, shards=1):
        weight_map = {}
        for shard in range(shards):
            subset = {key: value for i, (key, value) in enumerate(state.items()) if i % shards == shard}
            filename = f"model-{shard}.safetensors"
            save_file(subset, str(self.root / filename))
            weight_map.update({key: filename for key in subset})
        (self.root / "model.safetensors.index.json").write_text(json.dumps({"weight_map": weight_map}))
        return loader.checkpoint_metadata(self.root)

    def model(self, count=5):
        model = torch.nn.Module()
        model.blocks = torch.nn.ModuleList([
            torch.nn.Linear(7, 11, device="meta", dtype=torch.bfloat16) for _ in range(count)
        ])
        model.register_buffer("rope", torch.tensor([0.125, 0.5]), persistent=False)
        return model

    def state(self, model):
        return {name: torch.arange(value.numel()).reshape(value.shape).to(torch.bfloat16)
                for name, value in model.named_parameters()}

    def test_stream_matches_checkpoint_and_releases_each_cpu_view(self):
        model = self.model(20)
        state = self.state(model)
        state["mtp.aux.weight"] = torch.ones(3, dtype=torch.bfloat16)
        specs = self.checkpoint(state, shards=9)
        refs, buffers, sizes = [], set(), []
        original = torch.frombuffer

        def track(view, **kwargs):
            self.assertTrue(all(ref() is None for ref in refs), "CPU staging tensor retained")
            sizes.append(len(view))
            buffers.add(id(view.obj))
            tensor = original(view, **kwargs)
            refs.append(weakref.ref(tensor))
            return tensor

        with patch.object(torch, "frombuffer", side_effect=track):
            loader.stream_into_meta_model(model, specs, device="cpu", chunk_bytes=32,
                                          ignored_keys={"mtp.aux.weight"})
        self.assertGreater(len(refs), len(state))
        self.assertTrue(all(ref() is None for ref in refs))
        self.assertEqual(len(buffers), 1, "staging buffer must be reused across the checkpoint")
        self.assertLessEqual(max(sizes), 32)
        for name, value in model.named_parameters():
            torch.testing.assert_close(value, state[name], rtol=0, atol=0)
            self.assertFalse(value.requires_grad)
        torch.testing.assert_close(model.rope, torch.tensor([0.125, 0.5]))
        self.assertEqual(model.rope.dtype, torch.float32)

    def test_bad_keys_shapes_or_dtype_fail_before_allocation(self):
        for issue in ("missing", "extra", "shape", "dtype"):
            with self.subTest(issue=issue):
                model = self.model(1)
                state = self.state(model)
                if issue == "missing":
                    del state["blocks.0.bias"]
                elif issue == "extra":
                    state["unreviewed.weight"] = torch.ones(1, dtype=torch.bfloat16)
                elif issue == "shape":
                    state["blocks.0.bias"] = torch.ones(12, dtype=torch.bfloat16)
                else:
                    state["blocks.0.bias"] = state["blocks.0.bias"].float()
                with patch.object(torch, "empty", side_effect=AssertionError("allocated before validation")):
                    with self.assertRaises(ValueError):
                        specs = self.checkpoint(state)
                        loader.stream_into_meta_model(model, specs, device="cpu", chunk_bytes=32)

    def test_truncated_and_path_traversal_fail(self):
        self.checkpoint(self.state(self.model(1)))
        shard = self.root / "model-0.safetensors"
        shard.write_bytes(shard.read_bytes()[:-2])
        with self.assertRaises(ValueError):
            loader.checkpoint_metadata(self.root)
        (self.root / "model.safetensors.index.json").write_text(
            json.dumps({"weight_map": {"x": "../escape.safetensors"}}))
        with self.assertRaisesRegex(ValueError, "invalid shard path"):
            loader.checkpoint_metadata(self.root)

    def test_duplicate_json_rejected(self):
        (self.root / "model.safetensors.index.json").write_text(
            '{"weight_map":{"x":"a.safetensors","x":"b.safetensors"}}')
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            loader.checkpoint_metadata(self.root)

    def test_unsupported_versions_fail_by_default(self):
        fake = SimpleNamespace(__version__="5.18.0", AutoConfig=None,
                               AutoModelForMultimodalLM=None, GenerationConfig=None)
        with patch.dict("sys.modules", {"transformers": fake,
                        "accelerate": SimpleNamespace(__version__="1.15.0")}), \
                patch.object(torch.cuda, "is_available", side_effect=AssertionError("GPU touched")):
            with self.assertRaisesRegex(RuntimeError, "requires Transformers 5.17"):
                loader.load_qwen_bf16(self.root)

    def test_corrupt_offsets_rejected(self):
        import struct
        self.checkpoint(self.state(self.model(1)))
        path = self.root / "model-0.safetensors"
        raw = path.read_bytes()
        size = struct.unpack("<Q", raw[:8])[0]
        header = json.loads(raw[8:8 + size])
        entry = next(iter(header.values()))
        entry["data_offsets"][0] += 2
        encoded = json.dumps(header).encode()
        path.write_bytes(struct.pack("<Q", len(encoded)) + encoded + raw[8 + size:])
        with self.assertRaisesRegex(ValueError, "invalid tensor extent"):
            loader.checkpoint_metadata(self.root)

    def test_short_reads_and_scalar_tensor(self):
        import io
        class ShortReader(io.BytesIO):
            def readinto(self, view):
                return super().readinto(view[:2])
        target = torch.empty((5,), dtype=torch.bfloat16)
        source = torch.arange(5).to(torch.bfloat16)
        reader = ShortReader(source.view(torch.uint8).numpy().tobytes())
        loader._copy_tensor(reader, 0, target, bytearray(4), lambda: None)
        torch.testing.assert_close(source, target, rtol=0, atol=0)
        model = torch.nn.Module()
        model.scalar = torch.nn.Parameter(torch.empty((), device="meta", dtype=torch.bfloat16))
        specs = self.checkpoint({"scalar": torch.tensor(3.5, dtype=torch.bfloat16)})
        loader.stream_into_meta_model(model, specs, device="cpu", chunk_bytes=2)
        self.assertEqual(model.scalar.item(), 3.5)

    def test_headroom_guard_aborts_without_allocation(self):
        model = self.model(1)
        specs = self.checkpoint(self.state(model))
        with patch.object(torch, "empty", side_effect=AssertionError("allocated")):
            with self.assertRaisesRegex(RuntimeError, "headroom"):
                loader.stream_into_meta_model(model, specs, device="cpu",
                    guard=lambda: (_ for _ in ()).throw(RuntimeError("headroom")))

    def test_read_failure_closes_file_and_never_assigns_partial_tensor(self):
        model = self.model(1)
        specs = self.checkpoint(self.state(model))
        shard = self.root / "model-0.safetensors"
        shard.write_bytes(shard.read_bytes()[:8])
        opened = []
        original = Path.open

        def track(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            opened.append(result)
            return result

        with patch.object(Path, "open", track):
            with self.assertRaisesRegex(ValueError, "truncated"):
                loader.stream_into_meta_model(model, specs, device="cpu", chunk_bytes=32)
        self.assertTrue(all(file.closed for file in opened))
        self.assertTrue(all(value.is_meta for value in model.parameters()))


if __name__ == "__main__":
    unittest.main()
