#!/usr/bin/env python3
"""WVC-only synthetic curriculum using the unchanged production packet builders."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import runpy
import sys
from collections import Counter

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'src'))
from ai_bridge.domains.wvc.profiles import analysis_v12 as full
from ai_bridge.domains.wvc.profiles import analysis_v12_1 as schema
from ai_bridge.domains.wvc.profiles import analysis_v12_2 as current

HERE = Path(__file__).resolve().parent
SOURCES = ['src/ai_bridge/domains/wvc/profiles/analysis_v12.py',
           'src/ai_bridge/domains/wvc/profiles/analysis_v12_1.py',
           'src/ai_bridge/domains/wvc/profiles/analysis_v12_2.py',
           'tests/test_analysis_v12_1.py', 'tests/test_analysis_v12_2.py']
CHANNELS = ['pm1_0_ug_m3', 'pm2_5_ug_m3', 'pm4_0_ug_m3', 'pm10_0_ug_m3',
            'voc_index', 'nox_index', 'temperature_celsius', 'humidity_percent']
# Families describe complete trajectories, not random row IDs. All variants and
# both task modes of one family stay together. Evaluation curves are held out.
FAMILIES = {
 'train': ['stable', 'falling', 'pm_rise', 'voc_rise', 'nox_rise', 'mixed', 'zones', 'climate'],
 'holdout': ['delayed_rise', 'early_drop_plateau', 'voc_acceleration', 'climate_cycle'],
 'challenge': ['pm_drop_nox_late_rise', 'zone_opposition', 'transient_recovery', 'reversed_slope'],
}
FORBIDDEN = re.compile(r'electronic|elektroni|\becu\b|\bpcb\b|mosfet|automotive|electronics.foundation|automotive.specialization|p5[._-]\d|driver(?:s|ów)?\b', re.I)
FUTURE_SYSTEM = '''TASK=WVC_FUTURE_EXTENDED_V1. Tryb poza produkcją. Zwróć JSON analizy operatorskiej: task, environmental_attention, observations, deterministic_facts, interpretation_pl, limitations_pl, recommendation_pl. Każda obserwacja musi cytować fact_id i statystyki z pakietu. Stan zdrowia, jakość danych i alarmy opisuj wyłącznie na podstawie przekazanych zweryfikowanych faktów. SEN55 mierzy PM1/PM2.5/PM4/PM10, VOC Index, NOx Index, temperaturę i wilgotność w dwóch strefach. first i last to próbki na krańcach okna, delta=last-first, mean to średnia próbek, min/max to ekstrema, slope_per_minute to regresja całego okna, nie delta/15. Setpointy supply/extract 0-10 V są sygnałami zadanymi, nie airflow ani RPM. Bez przyczynowości i zgadywania źródła emisji. Łagodny klimat i brak baseline nie są samodzielnym powodem uwagi.'''


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def stats(values):
    times = [i * 5 / 60 for i in range(180)]  # 179 intervals, 895 s in a 15-min window
    mean = sum(values) / len(values)
    tm = sum(times) / len(times)
    slope = sum((t-tm)*(v-mean) for t,v in zip(times,values)) / sum((t-tm)**2 for t in times)
    return {k: round(v, 6) for k,v in dict(first=values[0], last=values[-1],
       delta=values[-1]-values[0], mean=mean, min=min(values), max=max(values),
       slope_per_minute=slope).items()} | {'count': 180, 'missing': 0}


def trajectory(family, node, channel, x):
    pollutant = channel in CHANNELS[:6]
    pm = channel in CHANNELS[:4]
    if family == 'falling' and pollutant: return 1-x
    if family == 'pm_rise' and pm: return x
    if family == 'voc_rise' and channel == 'voc_index': return x
    if family == 'nox_rise' and channel == 'nox_index': return x
    if family == 'mixed':
        if pm: return 1-x
        if channel == 'voc_index': return x
    if family == 'zones' and pm: return x if node == '2' else 1-x
    if family == 'climate' and not pollutant: return x*.03
    if family == 'delayed_rise' and pm: return max(0, (x-.7)/.3)
    if family == 'early_drop_plateau' and pollutant: return max(0, 1-x*4)
    if family == 'voc_acceleration' and channel == 'voc_index': return x*x
    if family == 'climate_cycle' and not pollutant: return math.sin(x*2*math.pi)*.02
    if family == 'pm_drop_nox_late_rise':
        if pm: return (1-x)**2
        if channel == 'nox_index': return max(0, (x-.8)/.2)
    if family == 'zone_opposition' and channel == 'voc_index': return x*x if node == '1' else (1-x)**2
    if family == 'transient_recovery' and pollutant: return max(0, 1-abs(x-.2)/.15)
    if family == 'reversed_slope' and pm:
        # last < first but whole-window regression rises; a mixed adverse window.
        return 1 if x == 0 else (0 if x < .65 else .6)
    return 0


def expected_ids(family, facts):
    relevant = []
    for f in facts:
        if f['kind'] != 'reading' or f['channel'] not in CHANNELS[:6]: continue
        if f['delta'] > 5 or f['slope_per_minute'] > .6:
            relevant.append(f['id'])
    return sorted(relevant)[:6]


def future_target(packet, env, selected):
    observations = []
    for f in env['facts']:
        if f['kind'] == 'reading':
            observations.append({'fact_id': f['id'], **{k:f[k] for k in ('first','last','delta','mean','min','max','slope_per_minute')}})
    deterministic = [f for f in full.build_fact_catalog(packet) if f['kind'] not in {'reading','setpoint','controller_mode'}]
    return {'task':'WVC_FUTURE_EXTENDED_V1', 'environmental_attention':bool(selected),
      'observations':observations, 'deterministic_facts':deterministic,
      'interpretation_pl': ('Występuje wzrost lub mieszany trend zanieczyszczeń w bieżącym oknie.' if selected else 'Brak utrzymującego się niekorzystnego trendu zanieczyszczeń w bieżącym oknie.'),
      'limitations_pl':'Brak historycznego baseline nie stanowi samodzielnego powodu uwagi. Setpointy supply/extract 0-10 V są sygnałami zadanymi, nie airflow ani RPM. VOC Index i NOx Index są indeksami czujnika. Nie ustalono źródła emisji ani związku przyczynowego ze sterowaniem. Slope jest regresją całego okna; delta opisuje wyłącznie różnicę last-first.',
      'recommendation_pl':'Obserwować kolejne okno i sprawdzić przekazane fakty jakości danych oraz stanu technicznego; bez automatycznej zmiany sterowania.'}


def generate(out):
    out.mkdir(parents=True, exist_ok=True)
    fixture = runpy.run_path(str(ROOT / 'tests/test_analysis_v12_1.py'))['_packet']
    for split, families in FAMILIES.items():
        rows=[]
        for fi, family in enumerate(families):
            count = 20 if split == 'train' else 10
            for variant in range(count):
                packet = copy.deepcopy(fixture())
                packet['window']['capture_span_seconds'] = 895
                packet['controller']['active_alarm_codes'] = []
                packet['controller']['active_alarm_sample_count'] = 0
                for node in ('1','2'):
                    readings={}
                    for ci, channel in enumerate(CHANNELS):
                        base = [3,5,7,10,40,20,21,45][ci] + variant*.1 + int(node)*.2
                        scale = [30,40,50,60,100,60,20,20][ci] * (1+variant*.01)
                        readings[channel] = stats([base+scale*trajectory(family,node,channel,i/179) for i in range(180)])
                    packet['sensor_bus']['nodes'][node]['readings'] = readings
                mode = ['MANUAL','AUTO','STOP'][variant % 3]
                packet['controller']['latest_mode'] = mode
                packet['controller']['mode_counts'] = {mode:180}
                for ch in ('supply_voltage','extract_voltage'):
                    voltage = 0 if mode == 'STOP' else variant % 11
                    packet['controller']['setpoints'][ch] = stats([voltage]*180)
                current_count = 13 if count == 20 else (7 if fi % 2 == 0 else 6)
                task = 'CURRENT' if variant < current_count else 'FUTURE'
                if task == 'FUTURE':
                    if variant % 3 == 0:
                        packet['sensor_bus']['nodes']['2']['measurement_stale_ratio'] = .25
                    elif variant % 3 == 1:
                        packet['controller']['active_alarm_codes']=['SENSOR_NODE_UNAVAILABLE']
                        packet['controller']['active_alarm_sample_count']=30
                    else:
                        packet['sensor_bus']['nodes']['1']['readings']['voc_index']['missing']=5
                        packet['sensor_bus']['nodes']['1']['readings']['voc_index']['count']=175
                env = current.build_environment_packet_from_compact(current.strip_alert_context(packet))
                selected = expected_ids(family, env['facts'])
                target = {'schema_version':1,'environmental_attention':bool(selected),'selected_fact_ids':selected}
                if task == 'CURRENT':
                    messages = current.build_environment_prompt_from_compact(packet)
                    system, user = [m['content'] for m in messages]
                else:
                    system = FUTURE_SYSTEM
                    user = dumps({'task':'WVC_FUTURE_EXTENDED_V1', 'verified':True, 'packet':packet,
                                  'facts':full.build_fact_catalog(packet)})
                    target = future_target(packet,env,selected)
                rows.append({'record_id':f'wvc-{family}-{variant:02}', 'domain':'WVC', 'family':family,
                  'task':task, 'source_paths':SOURCES, 'packet':packet,
                  'system':system, 'user':user, 'assistant':dumps(target)})
        (out/f'{split}.jsonl').write_text(''.join(dumps(r)+'\n' for r in rows))
    manifest={'adapter':'wvc-advisory-v1', 'base_model':'Qwen/Qwen3.8-27B', 'parent_adapter':None,
              'sources':[{'path':p,'sha256':digest(ROOT/p)} for p in SOURCES],
              'generator_sha256':digest(__file__), 'files':{}}
    for split in FAMILIES:
        path=out/f'{split}.jsonl'
        rows=[json.loads(l) for l in path.read_text().splitlines()]
        manifest['files'][split]={'path':path.name,'sha256':digest(path),'count':len(rows),
          'tasks':dict(Counter(r['task'] for r in rows)),
          'classes':dict(Counter(f"{r['task']}:{json.loads(r['assistant'])['environmental_attention']}" for r in rows)),
          'families':FAMILIES[split]}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return validate(out)


def validate(out):
    manifest=json.loads((out/'manifest.json').read_text())
    assert manifest['base_model']=='Qwen/Qwen3.8-27B' and manifest['parent_adapter'] is None
    assert manifest['generator_sha256']==digest(__file__)
    assert {s['path'] for s in manifest['sources']}==set(SOURCES)
    for source in manifest['sources']:
        assert source['sha256']==digest(ROOT/source['path'])
        assert not FORBIDDEN.search(source['path'])
    families=set(); packets=set(); ids=set()
    for split in FAMILIES:
        path=out/f'{split}.jsonl'
        assert manifest['files'][split]['sha256']==digest(path)
        rows=[json.loads(l) for l in path.read_text().splitlines()]
        assert len(rows)==manifest['files'][split]['count']
        split_families={r['family'] for r in rows}
        assert split_families==set(FAMILIES[split]) and not families & split_families
        families |= split_families
        local_packets=set()
        for row in rows:
            assert row['domain']=='WVC' and row['source_paths']==SOURCES
            assert not FORBIDDEN.search(dumps(row)), f"contamination: {row['record_id']}"
            assert row['record_id'] not in ids
            ids.add(row['record_id'])
            # Exclude timestamps/metadata: identical observations cannot cross splits.
            signature=dumps(row['packet']['sensor_bus']['nodes'])
            assert signature not in packets, 'cross-split trajectory duplicate'
            local_packets.add(signature)
            target=json.loads(row['assistant'])
            if row['task']=='CURRENT':
                decision=schema.EnvironmentalDecisionV121.model_validate(target,strict=True)
                schema.validate_environmental_decision(row['packet'],decision)
                assert set(target)=={'schema_version','environmental_attention','selected_fact_ids'}
                assert decision.environmental_attention or not decision.selected_fact_ids
                messages=current.build_environment_prompt_from_compact(row['packet'])
                assert [row['system'],row['user']]==[m['content'] for m in messages]
                assert not any(s in row['user'] for s in ('alarm','health','missing','FUTURE'))
                env=json.loads(row['user'].split('\n\n',1)[1])
                assert all(f['kind'] in {'reading','setpoint','controller_mode'} for f in env['facts'])
                assert all('missing' not in f and 'count' not in f for f in env['facts'])
                assert not row['packet']['controller']['active_alarm_codes']
            else:
                assert row['task']=='FUTURE' and row['system']==FUTURE_SYSTEM
                env=current.build_environment_packet_from_compact(row['packet'])
                assert target==future_target(row['packet'],env,expected_ids(row['family'],env['facts']))
        packets |= local_packets
    result={'contamination':'PASS','non_wvc_elements':0,'schema_current':'PASS','leakage':'PASS',
            'manifest_sha256':digest(out/'manifest.json'),'splits':manifest['files']}
    (out/'gates.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['generate','validate'])
    parser.add_argument('--output',type=Path,default=HERE/'data')
    args=parser.parse_args()
    print(json.dumps(generate(args.output) if args.action=='generate' else validate(args.output),indent=2))
