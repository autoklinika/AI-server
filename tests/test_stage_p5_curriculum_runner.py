from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "deploy/stage-p5/training/run_curriculum_calibration_v1.sh"
TRAINER = ROOT / "deploy/stage-p5/training/microtrain_lora_bf16.py"


def test_runner_uses_v2_and_serious_readiness_by_default():
    text = RUNNER.read_text()
    assert "automotive_curriculum_v2.jsonl" in text
    assert "P5_CALIBRATION_READINESS_LEVEL:-serious" in text
    assert "validate_curriculum_readiness_v1.py" in text
    assert "P5_CALIBRATION_MAX_LENGTH:-576" in text
    assert "--shuffle" in text


def test_trainer_shuffle_is_explicit_and_manifested():
    text = TRAINER.read_text()
    assert 'ap.add_argument("--shuffle", action="store_true")' in text
    assert "random.shuffle(rows)" in text
    assert '"shuffle": args.shuffle' in text
