"""Offline contract, mutation, and lease failure-path tests. No GPU or API calls."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'deploy/stage-p5/training/diagnostic_reasoning_v1'
sys.path.insert(0,str(HERE))
import curriculum as cur
import prepare_diagnostic_reasoning_v1 as prep
import validate_diagnostic_reasoning_v1 as val
import resource_guard as guard
import runtime_contract as runtime
import evaluate_diagnostic_reasoning_v1 as evaluator


def test_prepared_data_and_determinism():
    assert val.validate()['status']=='PASS'
    before={p.name:p.read_bytes() for p in HERE.glob('*.json*')}
    prep.prepare()
    assert before=={p.name:p.read_bytes() for p in HERE.glob('*.json*')}
    assert val.validate()['category_balance']==dict.fromkeys(cur.CATEGORIES,3)


def test_train_only_replay_is_verbatim_and_diverse():
    _,combined,_,sources=prep.build()
    for source in sources:
        original={r['record_id']:r for r in prep.read(HERE.parent/source['path'])}
        selected=[r for r in combined if r['metadata']['p512_origin']==source['origin']]
        assert len(selected)==source['count']
        assert len(source['categories'])>=min(8,source['count'])
        for row in selected:
            assert all(row[k]==original[row['record_id']][k] for k in ('system','user','assistant'))
            assert original[row['record_id']]['metadata']['split']=='train'


@pytest.mark.parametrize('mutation,match',[
    (lambda s:s.update(hypotheses=['jedna']), 'hypotheses'),
    (lambda s:s.update(hypotheses=['x']*6), 'hypotheses'),
    (lambda s:s.update(unknowns=[]), 'unknowns'),
    (lambda s:s.update(test=[s['test'],s['test']]), 'main test'),
    (lambda s:s['test'].update(instruction='Zmierz wszystko na płycie.'), 'endpoints'),
    (lambda s:s.update(branches=s['branches'][:1]), 'predicted branches'),
    (lambda s:s['branches'][1].update(interpretation=s['branches'][0]['interpretation']), 'non-discriminating'),
    (lambda s:s['branches'][1].update(next_step=''), 'next_step'),
    (lambda s:s.update(trap=''), 'trap'),
    (lambda s:s.update(non_conclusion=''), 'non_conclusion'),
])
def test_authored_spec_rejects_bad_reasoning(mutation,match):
    row=copy.deepcopy(cur.new_records()[0]); mutation(row['spec'])
    try: row['assistant']=cur.render(row['spec'])
    except (TypeError,KeyError): pass
    with pytest.raises((ValueError,TypeError),match=match+'|target/spec'): val.validate_spec(row)


@pytest.mark.parametrize('claim',[' Napięcie wynosi 7 V.',' Pin A12 jest zwarty.',' Wymień IRF1234.',' Winny jest tranzystor.'])
def test_new_target_claim_guard(claim):
    row=copy.deepcopy(cur.new_records()[0]); row['assistant']+=claim
    with pytest.raises(ValueError): val.guard_claims(row)


def test_rejects_answer_revealing_prompt():
    row=cur.new_records()[0]; row['user']+=' Uszkodzony jest driver.'
    with pytest.raises(ValueError,match='answer-revealing'): val.validate_spec(row)


@pytest.mark.parametrize('kind',['id','content','near','leak','balance','replay'])
def test_dataset_negative_contracts(kind):
    new,combined,smoke,_=copy.deepcopy(prep.build())
    if kind=='id': combined[1]['record_id']=combined[0]['record_id']
    if kind=='content': combined[1]['user']=combined[0]['user']
    if kind=='near': combined[1]['user']=combined[0]['user']+' Dodatkowe pytanie.'
    if kind=='leak': smoke[0]['user']=combined[0]['assistant']
    if kind=='balance': new[0]['metadata']['category']='other'
    if kind=='replay': combined[0]['metadata']['split']='holdout'
    with pytest.raises(ValueError): val.validate_rows(new,combined,smoke)


class Child:
    pid=12345
    def __init__(self): self.alive=True; self.waits=0
    def poll(self): return None if self.alive else 0
    def wait(self,timeout):
        self.waits+=1
        if self.alive and self.waits==1: raise subprocess.TimeoutExpired('fake',timeout)
        self.alive=False; return 0


def lease_fixture(monkeypatch,mode):
    calls=[]; child=Child(); killed=[]
    def api(base,method,path,body=None):
        calls.append((method,path,body))
        if path=='/status': return {'active_count':0,'admission_blocked':False,'gpu_residency':{'state':'llm','recovery_required':False}}
        if method=='DELETE': return {'released':True}
        if path.endswith('/heartbeat'):
            if mode=='heartbeat_error': raise OSError('offline')
            return {'lease_id':'unit-lease','state':'lost' if mode=='lost' else 'active'}
        return {'lease_id':'unit-lease','state':'queued' if mode=='queued' else 'active'}
    monkeypatch.setattr(guard.subprocess,'Popen',lambda *a,**kw:child)
    monkeypatch.setattr(guard.subprocess,'run',lambda *a,**kw:type('Result',(),{'returncode':0})())
    monkeypatch.setattr(guard.os,'killpg',lambda *a:killed.append(a))
    return calls,child,killed,api


@pytest.mark.parametrize('mode',['ok','lost','heartbeat_error','queued'])
def test_reservation_lifecycle(monkeypatch,tmp_path,mode):
    calls,child,killed,api=lease_fixture(monkeypatch,mode)
    invoke=lambda:guard.supervise('fake',tmp_path,['fake'],'test-container',api=api,preflight=lambda allow:{},interval=.001)
    if mode=='ok': assert invoke()==0
    else:
        with pytest.raises((RuntimeError,OSError)): invoke()
    assert calls[-1][:2]==('DELETE','/resource/leases/unit-lease')
    assert all('/uses' not in path for _,path,_ in calls)
    assert calls[1][2]['workload']=='llm'
    if mode in ('lost','heartbeat_error'): assert killed
    evidence=json.loads((tmp_path/'resource_lease.json').read_text())
    assert evidence[-1]['event']=='released'


def test_failed_preflight_cannot_reserve(tmp_path):
    def fail(allow): raise RuntimeError('ollama_model_resident')
    def forbidden(*args): pytest.fail('API must not be reached')
    with pytest.raises(RuntimeError,match='resident'):
        guard.supervise('fake',tmp_path,['fake'],'fake',api=forbidden,preflight=fail)


def test_only_explicit_stopped_comfy_is_allowed(tmp_path):
    p=tmp_path/'1'; p.mkdir(); (p/'status').write_text('State:\tT (stopped)\n')
    (p/'cgroup').write_text('0::/system.slice/comfyui.service\n')
    guard.check_owners([1],True,tmp_path)
    with pytest.raises(RuntimeError): guard.check_owners([1],False,tmp_path)
    (p/'status').write_text('State:\tS (sleeping)\n')
    with pytest.raises(RuntimeError): guard.check_owners([1],True,tmp_path)
    (p/'status').write_text('State:\tT (stopped)\n')
    (p/'cgroup').write_text('0::/system.slice/other.service\n')
    with pytest.raises(RuntimeError): guard.check_owners([1],True,tmp_path)


def test_schedule_and_runtime_shell_contracts():
    import ast
    trainer=(HERE/'train_diagnostic_reasoning_v1.py').read_text()
    tree=ast.parse(trainer)
    scope={}
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('EXPECTED_RECORDS','EXPECTED_OPTIMIZER_STEPS','GROUP_SIZES') for t in node.targets):
            exec(compile(ast.Module(body=[node],type_ignores=[]),'schedule','exec'),scope)
    assert scope['GROUP_SIZES']==[4]*40
    assert sum(scope['GROUP_SIZES'])==scope['EXPECTED_RECORDS']==160
    assert scope['EXPECTED_OPTIMIZER_STEPS']==40
    assert 'torch.optim.AdamW' in trainer and 'refusing assistant-target truncation' in trainer
    assert 'merge_and_unload' not in trainer
    runner=(HERE/'run_diagnostic_reasoning_v1.sh').read_text()
    conversion=(ROOT/'deploy/stage-p5/runtime/build_qwen38_p512_runtime.sh').read_text()
    for name,value in [('OPT_STEPS','40'),('MAX_LENGTH','768'),('LORA_R','8'),('LR','0.00001')]: assert f'{name}={value}\n' in runner
    for marker in ['MES','GPUVM','GPU reset','telemetry_unreadable','P512_LEASE_ID','resource_guard.py','HSA_USE_SVM=0']: assert marker in runner
    assert 'qwen3.8:27b-p4-64k-gpu-p512-dev' in conversion
    assert 'runtime_contract.py' in conversion and 'read -r EXPECTED_ADAPTER_SHA EXPECTED_TENSORS' in conversion
    for text in (runner,conversion):
        assert 'systemctl' not in text and 'mv -Tf' not in text and 'ln -s' not in text
    for path in [HERE/'run_diagnostic_reasoning_v1.sh',ROOT/'deploy/stage-p5/runtime/build_qwen38_p512_runtime.sh']:
        subprocess.run(['bash','-n',str(path)],check=True)


def test_scoring_is_auditable_and_never_accepts_quality():
    row=prep.build()[2][0]
    result=evaluator.score('Wymień ABC123, to rozwiąże problem.',row)
    assert result['unsupported_guess_flag']
    assert not result['criteria']['unsupported_component_guess']
    assert not result['criteria']['high_information_next_measurement']
    assert result['quality_acceptance'].startswith('PENDING')
    assert not evaluator.score('Hipotezy: przeciążenie.',row)['criteria']['hypotheses']


def make_adapter(tmp_path):
    import struct
    header=json.dumps({'tensor':{'dtype':'BF16','shape':[1],'data_offsets':[0,2]}}).encode()
    (tmp_path/'adapter_model.safetensors').write_bytes(struct.pack('<Q',len(header))+header+b'\0\0')
    (tmp_path/'adapter_config.json').write_text('{"r":8}')
    m=dict(stage='P5.12',parent_stage='P5.11',adapter_kind='standalone_lora_not_merged',base_model='Qwen/Qwen3.8-27B',
        status='TRAINING_INTEGRITY_PASS_QUALITY_PENDING',quality_acceptance='PENDING_POST_TRAINING_SMOKE',
        host_watchdog_status='PASS',lease_status_final='released',lease_id='fixture',lease_status_at_start='active',
        parent_adapter_realpath='/srv/ai-data/training/p5/adapters/automotive-specialization-v1/fixture',parent_adapter_sha256='0'*64,
        config=dict(lora_r=8,max_length=768,lr=1e-5,microsteps=160,optimizer_steps=40,group_sizes=[4]*40,fresh_optimizer=True,base_dtype='bfloat16'),
        microsteps=[{}]*160,optimizer_steps=[{}]*40,token_contract={'truncated_records':0},gpu_error_baseline=0,gpu_error_final=0,
        dataset_sha256=runtime.digest(HERE/'diagnostic_reasoning_v1_replay_train.jsonl'),
        adapter_sha256=runtime.digest(tmp_path/'adapter_model.safetensors'),adapter_tensor_count=1)
    (tmp_path/'p512_training_manifest.json').write_text(json.dumps(m))
    return m


def test_runtime_reads_dynamic_hash_and_count(tmp_path):
    m=make_adapter(tmp_path)
    assert runtime.validate_adapter(tmp_path)['adapter_tensor_count']==1
    (tmp_path/'adapter_model.safetensors').write_bytes(b'changed')
    with pytest.raises(ValueError,match='SHA'): runtime.validate_adapter(tmp_path)


@pytest.mark.parametrize('field,value',[
    ('stage','P5.11'),('adapter_kind','merged'),('host_watchdog_status','FAILED'),
    ('lease_status_final','active'),('adapter_tensor_count',992),('gpu_error_final',1),
    ('quality_acceptance','ACCEPTED'),('dataset_sha256','0'*64),
])
def test_runtime_rejects_invalid_artifacts(tmp_path,field,value):
    m=make_adapter(tmp_path); m[field]=value
    (tmp_path/'p512_training_manifest.json').write_text(json.dumps(m))
    with pytest.raises(ValueError): runtime.validate_adapter(tmp_path)


def test_exact_token_evidence_is_current():
    report=json.loads((HERE/'token_validation.json').read_text())
    assert report['dataset_sha256']==prep.sha(HERE/prep.FILES[1])
    assert report['records']==160 and report['max_tokens']<=768
    assert report['truncated_records']==0
    assert len(report['lengths'])==160
    trainer=(HERE/'train_diagnostic_reasoning_v1.py').read_text()
    assert trainer.count('enable_thinking=False')==4
    assert 'chat template prefix mismatch' in trainer


def test_failed_child_releases_lease(monkeypatch,tmp_path):
    calls,child,killed,api=lease_fixture(monkeypatch,'ok')
    def failed(timeout): child.alive=False; return 17
    child.wait=failed
    assert guard.supervise('fake',tmp_path,['fake'],'fake',api=api,preflight=lambda allow:{})==17
    assert calls[-1][0]=='DELETE'


def test_signal_cleanup_releases_lease(monkeypatch,tmp_path):
    import signal
    calls,child,killed,api=lease_fixture(monkeypatch,'ok')
    def interrupt(timeout):
        child.alive=False
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
    child.wait=interrupt
    with pytest.raises(RuntimeError,match='interrupted'):
        guard.supervise('fake',tmp_path,['fake'],'fake',api=api,preflight=lambda allow:{})
    assert calls[-1][0]=='DELETE'


def test_release_failure_is_not_success(monkeypatch,tmp_path):
    calls,child,killed,api=lease_fixture(monkeypatch,'ok')
    def unavailable(base,method,path,body=None):
        if method=='DELETE':
            calls.append((method,path,body)); raise OSError('release offline')
        return api(base,method,path,body)
    with pytest.raises(RuntimeError,match='release failed'):
        guard.supervise('fake',tmp_path,['fake'],'fake',api=unavailable,preflight=lambda allow:{})
    assert sum(method=='DELETE' for method,_,_ in calls)==3


def test_resource_manager_unhealthy_blocks():
    for status in ({}, {'admission_blocked':True}, {'admission_blocked':False,'gpu_residency':{'state':'blocked','recovery_required':True}}):
        with pytest.raises(RuntimeError): guard.check_manager(status)
