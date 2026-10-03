"""Offline P5.13 WVC curriculum/training/runtime contracts. No GPU calls."""
import ast
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/"deploy/stage-p5/training/wvc_specialization_v1"
sys.path.insert(0,str(HERE))
import curriculum
import prepare_wvc_specialization_v1 as prep
import validate_wvc_specialization_v1 as val

FROZEN_SHA="ae70251542d5d69ebac94d83b995238ea869e7e0282d62ed19d2f7501573e22a"

def test_wvc_dataset_is_ready_deterministic_and_protected():
    report=val.validate()
    assert report["status"]=="PASS"
    assert report["new_records"]==96
    assert report["replay_records"]==64
    assert report["combined_records"]==160
    assert report["smoke_records"]==12
    assert report["category_balance"]==dict.fromkeys(curriculum.CATEGORIES,6)
    assert report["protected_eval_guard"]["available"] is True
    assert report["protected_eval_guard"]["corpus_sha256"]==FROZEN_SHA
    assert report["protected_eval_guard"]["max_question_similarity"] < val.PROTECTED_QUESTION_THRESHOLD
    manifest=json.loads((HERE/"wvc_specialization_v1.manifest.json").read_text())
    assert manifest["protected_eval_material_used"] is False
    assert manifest["protected_eval"]["sha256"]==FROZEN_SHA
    before={p.name:p.read_bytes() for p in HERE.glob("*.json*")}
    prep.prepare()
    after={p.name:p.read_bytes() for p in HERE.glob("*.json*")}
    assert before==after

def test_wvc_parent_and_replay_contract():
    new,combined,smoke,sources=prep.build()
    assert len(new)==96 and len(combined)==160 and len(smoke)==12
    manifest=json.loads((HERE/"wvc_specialization_v1.manifest.json").read_text())
    assert manifest["parent_stage"]=="P5.11"
    assert manifest["parent_adapter"].endswith("/automotive-specialization-v1/current")
    assert manifest["adapter_kind"]=="standalone_lora_not_merged"
    assert manifest["replay_fraction"]==0.4
    for source in sources:
        original={r["record_id"]:r for r in prep.read(HERE.parent/source["path"])}
        selected=[r for r in combined if r["metadata"]["p513_origin"]==source["origin"]]
        assert len(selected)==source["count"]
        for row in selected:
            assert row["metadata"]["split"]=="train"
            assert all(row[k]==original[row["record_id"]][k] for k in ("system","user","assistant"))

def test_wvc_targets_enforce_reasoning_boundaries():
    required=("OBSERWACJA:","HIPOTEZY:","NIE WYNIKA:",
              "NAJLEPSZE NASTĘPNE SPRAWDZENIE:","JEŚLI A:","JEŚLI B:","BRAKI/PEWNOŚĆ:")
    for row in curriculum.new_records():
        assert all(marker in row["assistant"] for marker in required)
        val.validate_spec(row)

def test_exact_token_evidence_is_frozen():
    report=json.loads((HERE/"token_validation.json").read_text())
    assert report["stage"]=="P5.13"
    assert report["adapter_id"]=="wvc-specialization-v1"
    assert report["dataset_sha256"]==prep.sha(HERE/prep.FILES[1])
    assert report["records"]==160
    assert report["max_tokens"]<=768
    assert report["truncated_records"]==0
    assert len(report["lengths"])==160

def test_training_schedule_and_no_merge():
    trainer=(HERE/"train_wvc_specialization_v1.py").read_text()
    tree=ast.parse(trainer)
    scope={}
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(
            isinstance(t,ast.Name) and t.id in ("EXPECTED_RECORDS","EXPECTED_OPTIMIZER_STEPS","GROUP_SIZES")
            for t in node.targets
        ):
            exec(compile(ast.Module(body=[node],type_ignores=[]),"schedule","exec"),scope)
    assert scope["EXPECTED_RECORDS"]==160
    assert scope["EXPECTED_OPTIMIZER_STEPS"]==40
    assert scope["GROUP_SIZES"]==[4]*40
    assert "merge_and_unload" not in trainer
    assert "PENDING_WVC_BASELINE_REVIEW" in trainer
    assert "parent must be standalone P5.11" in trainer

def test_runner_and_runtime_are_dev_only_and_fail_closed():
    runner=(HERE/"run_wvc_specialization_v1.sh").read_text()
    builder=(ROOT/"deploy/stage-p5/runtime/build_qwen38_p513_wvc_runtime.sh").read_text()
    evaluator=(ROOT/"deploy/stage-p5/evaluation/replay_frozen_wvc_p513.py").read_text()
    for marker in ("MES","GPUVM","GPU reset","telemetry_unreadable",
                   "P513_LEASE_ID","resource_guard.py","HSA_USE_SVM=0"):
        assert marker in runner
    assert "qwen3.8:27b-p4-64k-gpu-p513-wvc-dev" in builder
    assert "PENDING_WVC_BASELINE_REVIEW" in builder
    assert FROZEN_SHA in evaluator
    assert "semantic_authority" in evaluator and "manual review" in evaluator
    for text in (runner,builder):
        assert "systemctl" not in text
        assert "merge_and_unload" not in text
    subprocess.run(["bash","-n",str(HERE/"run_wvc_specialization_v1.sh")],check=True)
    subprocess.run(["bash","-n",str(ROOT/"deploy/stage-p5/runtime/build_qwen38_p513_wvc_runtime.sh")],check=True)
