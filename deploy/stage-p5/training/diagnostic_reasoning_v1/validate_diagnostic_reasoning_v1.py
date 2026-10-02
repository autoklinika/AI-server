#!/usr/bin/env python3
"""Fail-closed dataset contract. Similarity gates supplement, not prove, quality."""
import json
import re
from collections import Counter
from itertools import combinations
from curriculum import CATEGORIES, render
from prepare_diagnostic_reasoning_v1 import HERE, FILES, QUALITY, build, read, sha

NEAR_THRESHOLD=.78
LEAK_THRESHOLD=.55

def require(value,message):
    if not value: raise ValueError(message)

def normalize(text): return ' '.join(re.findall(r'\w+',text.casefold()))
def shingles(text,n=5):
    words=normalize(text).split()
    return {tuple(words[i:i+n]) for i in range(max(0,len(words)-n+1))}
def similarity(a,b): return len(a & b)/max(1,len(a | b))
def guard_claims(row):
    target=row['assistant']
    # New targets intentionally carry no numeric claims; any future number needs
    # an explicit authoring-policy change, not an automatically inferred allowance.
    require(not re.search(r'\d|\b(?:pin|piny|nóżka)\s*[:#]?\s*[A-Z]?\d+',target,re.I),'invented numeric/pin claim')
    require(not re.search(r'\b(?:[A-Z]{2,}\d+[A-Z\d-]*|[RCLUQDJ]\d+)\b',target),'invented part number')
    require(not re.search(r'\b(?:wymień|wymienić należy|uszkodzony jest|winny jest)\b',target,re.I),'unsupported component guess')

def validate_spec(row):
    s=row['spec']
    for field in ('observation','known_facts','physical_model','trap','non_conclusion','confidence','context'):
        require(isinstance(s.get(field),str) and len(s[field])>15,'missing '+field)
    hs=s.get('hypotheses',[])
    require(2<=len(hs)<=5 and len(set(hs))==len(hs),'hypotheses must contain 2-5 distinct alternatives')
    require(s.get('unknowns') and all(len(x)>15 for x in s['unknowns']),'explicit unknowns required')
    test=s.get('test'); require(isinstance(test,dict),'exactly one main test required')
    require(set(test)=={'quantity','points','condition','instruction'},'main test schema')
    require(len(test['points'])==2 and len(set(test['points']))==2,'test must straddle a physical boundary')
    require(all(p in test['instruction'] for p in test['points']),'test lacks specified endpoints')
    require(len(test['condition'])>20 and len(test['quantity'])>8,'test lacks controlled contrast')
    require(any(x in test['instruction'] for x in ('równocześnie','równoczesny','różnicę')),'generic measurement list')
    require(not re.search(r'zmierz wszystko|sprawdź elementy|lista pomiarów',test['instruction'],re.I),'generic measurement list')
    bs=s.get('branches',[]); require(len(bs)>=2,'at least two predicted branches required')
    require({b['hypothesis'] for b in bs}==set(range(len(hs))),'predictions must distinguish competing hypotheses')
    for field in ('result','interpretation','next_step'):
        require(all(len(b.get(field,''))>25 for b in bs),'missing branch '+field)
        require(len({normalize(b[field]) for b in bs})==len(bs),'non-discriminating '+field)
    require('A:' in bs[0]['result'] and 'B:' in bs[1]['result'],'both result directions required')
    require(any(x in bs[0]['result'] for x in ('tylko','różnica')) and any(x in bs[1]['result'] for x in ('oba','przed')),'result contrast does not localize boundary')
    require(all(any(x in b['next_step'].lower() for x in ('zmierz','zarejestruj','sprawdź','porównaj')) for b in bs),'next measurements required')
    require(any(x in s['non_conclusion'] for x in ('Nie można','nie wiadomo')),'non-conclusion missing')
    require(not re.search(r'uszkodzony|zwarty element|wymieniono|przerwana ścieżka',row['user'],re.I),'answer-revealing/easy prompt')
    require(s['context'] in row['user'] and s['observation'] in row['user'],'unsupported observed fact')
    if s['good_channel_applicable']:
        require('sprawnym kanałem' in test['instruction'] and 'samej komendzie' in test['instruction'],'uncontrolled good-channel reference')
    require(row['assistant']==render(s),'target/spec drift')
    guard_claims(row)

def validate_rows(new,combined,smoke):
    require((len(new),len(combined),len(smoke))==(96,160,12),'row counts')
    require(Counter(r['metadata']['category'] for r in new)==Counter({c:3 for c in CATEGORIES}),'category balance')
    require(len({r['record_id'] for r in combined+smoke})==172,'duplicate IDs')
    for view in ('user','assistant'):
        values=[normalize(r[view]) for r in combined if view in r]
        require(len(values)==len(set(values)),'exact duplicate '+view)
    require({r['record_id'] for r in new}=={r['record_id'] for r in combined if r['metadata'].get('p512_origin')=='new'},'new rows missing')
    require(all(r['metadata']['split']=='train' and r['metadata'].get('training_eligible',True) for r in combined),'non-train leakage')
    require(all(r['metadata']['split']=='smoke' and r['metadata']['training_eligible'] is False for r in smoke),'smoke eligibility')
    require(Counter(r['metadata']['p512_origin'] for r in combined)==Counter(new=96,automotive=32,electronics_v1=10,electronics_v2=11,electronics_v3=11),'replay composition')
    for row in new: validate_spec(row)
    max_near=0; closest=None
    # Compare prompts AND targets separately; boilerplate system instructions excluded.
    for field in ('user','assistant'):
        ss=[shingles(r[field]) for r in combined]
        for i,j in combinations(range(len(combined)),2):
            sim=similarity(ss[i],ss[j])
            if sim>max_near: max_near=sim; closest=[combined[i]['record_id'],combined[j]['record_id'],field]
            require(sim<NEAR_THRESHOLD,f'near duplicate {field}: {combined[i]["record_id"]} / {combined[j]["record_id"]}: {sim:.3f}')
    max_leak=0
    for s in smoke:
        require(len(s['user'])>150,'too-easy smoke prompt')
        require(set(s['expected_anchors'])=={'hypotheses','discriminating_test','result_a','result_b','next_a','next_b','missing_data','observation_vs_inference','unsupported_component_guess','good_channel'},'smoke scoring metadata')
        for r in combined:
            for field in ('user','assistant'):
                sim=similarity(shingles(s['user']),shingles(r[field])); max_leak=max(max_leak,sim)
                require(sim<LEAK_THRESHOLD,'smoke-vs-train leakage')
        require(all(normalize(s['user'])!=normalize(t['user']) for t in smoke if t['record_id']!=s['record_id']),'duplicate smoke content')
    return dict(status='PASS',new_records=96,replay_records=64,combined_records=160,smoke_records=12,replay_fraction=.40,
                category_balance={c:3 for c in CATEGORIES},max_near_similarity=round(max_near,6),closest_pair=closest,
                max_smoke_train_similarity=round(max_leak,6),near_threshold=NEAR_THRESHOLD,leak_threshold=LEAK_THRESHOLD,
                quality_acceptance=QUALITY)

def validate():
    new,combined,smoke=[read(HERE/f) for f in FILES]
    report=validate_rows(new,combined,smoke)
    expected=build()
    require((new,combined,smoke)==expected[:3],'deterministic authoring/replay provenance mismatch')
    m=json.loads((HERE/'diagnostic_reasoning_v1.manifest.json').read_text())
    require(m['files']=={f:sha(HERE/f) for f in FILES},'dataset SHA mismatch')
    require(m['sources']==expected[3],'replay source SHA/selection mismatch')
    require(m['authoring_sha256']=={f:sha(HERE/f) for f in ('curriculum.py','smoke_cases.py')},'authoring SHA mismatch')
    require(m['quality_acceptance']==QUALITY and m['protected_eval_material_used'] is False,'quality boundary')
    require(m['validation']==report,'validation manifest drift')
    return report
if __name__=='__main__':
    print(json.dumps(validate(),ensure_ascii=False,sort_keys=True))
    print('P5_12_DIAGNOSTIC_READINESS=PASS')
