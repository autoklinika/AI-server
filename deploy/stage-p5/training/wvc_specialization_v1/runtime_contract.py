#!/usr/bin/env python3
"""CPU-only P5.13 artifact validation used before DEV conversion."""
import hashlib
import json
from pathlib import Path
import struct
import sys

def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def validate_adapter(path):
    path=Path(path)
    m=json.loads((path/'p513_training_manifest.json').read_text())
    expected={'stage':'P5.13','adapter_id':'wvc-specialization-v1','parent_stage':'P5.11',
        'adapter_kind':'standalone_lora_not_merged','base_model':'Qwen/Qwen3.8-27B',
        'status':'TRAINING_INTEGRITY_PASS_QUALITY_PENDING','quality_acceptance':'PENDING_WVC_BASELINE_REVIEW',
        'host_watchdog_status':'PASS','lease_status_final':'released'}
    for key,value in expected.items():
        if m.get(key)!=value: raise ValueError('invalid manifest '+key)
    c=m['config']
    for key,value in dict(lora_r=8,max_length=768,lr=1e-5,microsteps=160,optimizer_steps=40,
                          group_sizes=[4]*40,fresh_optimizer=True,base_dtype='bfloat16').items():
        if c.get(key)!=value: raise ValueError('invalid config '+key)
    if len(m['microsteps'])!=160 or len(m['optimizer_steps'])!=40: raise ValueError('incomplete training')
    if m['token_contract']['truncated_records']!=0: raise ValueError('truncated training')
    if m['gpu_error_baseline']!=m['gpu_error_final']: raise ValueError('GPU errors')
    if not m.get('lease_id') or m.get('lease_status_at_start')!='active': raise ValueError('missing lease evidence')
    if not m.get('parent_adapter_realpath') or len(m.get('parent_adapter_sha256',''))!=64: raise ValueError('missing parent provenance')
    if m.get('protected_eval_sha256')!='ae70251542d5d69ebac94d83b995238ea869e7e0282d62ed19d2f7501573e22a':
        raise ValueError('protected WVC baseline identity mismatch')
    dataset=Path(__file__).parent/'wvc_specialization_v1_replay_train.jsonl'
    if m['dataset_sha256']!=digest(dataset): raise ValueError('dataset SHA mismatch')
    weights=path/'adapter_model.safetensors'
    if m['adapter_sha256']!=digest(weights): raise ValueError('adapter SHA mismatch')
    with weights.open('rb') as f:
        size=struct.unpack('<Q',f.read(8))[0]
        if size>16*1024*1024: raise ValueError('invalid safetensors header')
        header=json.loads(f.read(size))
    count=len([k for k in header if k!='__metadata__'])
    if count<=0 or count!=m['adapter_tensor_count']: raise ValueError('tensor count mismatch')
    if json.loads((path/'adapter_config.json').read_text())['r']!=8: raise ValueError('rank mismatch')
    return m
if __name__=='__main__':
    m=validate_adapter(sys.argv[1]); print(m['adapter_sha256'],m['adapter_tensor_count'])
