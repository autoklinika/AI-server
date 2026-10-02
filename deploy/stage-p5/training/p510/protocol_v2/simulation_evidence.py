#!/usr/bin/env python3
"""Deterministic P5.10 simulation evidence PoC.

Verifies mathematical ground truth for eight quarantined causal families, one per
capability domain. It is NOT an independence, P5-exposure, real-world, evaluation,
training, or final-access certificate.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATUS = "SIMULATION_VERIFIED_QUARANTINE"
SELECTED = {
    "PI01": "power_integrity",
    "AS01": "analog_sensor_chain",
    "AP01": "actuator_power_stage",
    "DT01": "digital_timing_reset",
    "VN01": "vehicle_network",
    "PF01": "pcb_fault_localization",
    "IE01": "intermittent_environmental",
    "ES01": "ecu_system_isolation",
}

def q(x: float) -> float:
    return round(float(x), 12)

def _pi01():
    vs, r = 12.0, 0.25
    i_low, i_high = 1.0, 4.0
    v_low, v_high = vs-i_low*r, vs-i_high*r
    bypass = vs-i_high*0.0
    return {
        "model_kind":"ohms_law_series_drop",
        "equation":"Vrail = Vs - Iload*Rcontact",
        "inputs":{"Vs_V":vs,"Rcontact_ohm":r,"I_low_A":i_low,"I_high_A":i_high},
        "observables":{"Vrail_low_V":q(v_low),"Vrail_high_V":q(v_high),"Vrail_bypass_V":q(bypass)},
        "invariant":"higher load increases contact drop; bypass removes the drop",
        "oracle_pass": (v_high < v_low < bypass and math.isclose(vs-v_high, i_high*r)),
        "metamorphic_pass": math.isclose(bypass, vs),
    }

def _as01():
    vin, vprev, rs, c = 2.0, 4.5, 10000.0, 20e-12
    t1, t2 = 0.1e-6, 1.0e-6
    tau=rs*c
    v1=vin+(vprev-vin)*math.exp(-t1/tau)
    v2=vin+(vprev-vin)*math.exp(-t2/tau)
    e1,e2=abs(v1-vin),abs(v2-vin)
    return {
        "model_kind":"first_order_sar_settling",
        "equation":"Vcap(t)=Vin+(Vprev-Vin)*exp(-t/(Rs*Csample))",
        "inputs":{"Vin_V":vin,"Vprev_V":vprev,"Rs_ohm":rs,"Csample_F":c,"t_short_s":t1,"t_long_s":t2},
        "observables":{"error_short_V":q(e1),"error_long_V":q(e2),"tau_s":q(tau)},
        "invariant":"settling error decays monotonically with acquisition time",
        "oracle_pass": (e2 < e1 and e2 >= 0),
        "metamorphic_pass": abs((vin+(vin-vin)*math.exp(-t1/tau))-vin) < 1e-15,
    }

def _ap01():
    L,I0,vcl1,vcl2 = 0.020, 2.0, 12.0, 36.0
    t1=L*I0/vcl1
    t2=L*I0/vcl2
    return {
        "model_kind":"inductor_constant_clamp_decay",
        "equation":"t_zero = L*I0/Vclamp for constant opposing clamp",
        "inputs":{"L_H":L,"I0_A":I0,"Vclamp_low_V":vcl1,"Vclamp_high_V":vcl2},
        "observables":{"t_low_clamp_s":q(t1),"t_high_clamp_s":q(t2)},
        "invariant":"larger opposing clamp voltage shortens current-decay time",
        "oracle_pass": t2 < t1 and math.isclose(t1/t2, vcl2/vcl1),
        "metamorphic_pass": math.isclose((2*L)*I0/(2*vcl1), t1),
    }

def _dt01():
    tmin,tmax=0.4,0.9
    early,valid,late=0.2,0.6,1.1
    classify=lambda t: "EARLY_FAULT" if t<tmin else ("VALID" if t<=tmax else "LATE_FAULT")
    return {
        "model_kind":"window_watchdog_state_machine",
        "equation":"service valid iff tmin <= t_service <= tmax",
        "inputs":{"tmin_s":tmin,"tmax_s":tmax,"early_s":early,"valid_s":valid,"late_s":late},
        "observables":{"early":classify(early),"valid":classify(valid),"late":classify(late)},
        "invariant":"frequent activity can still fault when service occurs before the legal window",
        "oracle_pass": classify(early)=="EARLY_FAULT" and classify(valid)=="VALID" and classify(late)=="LATE_FAULT",
        "metamorphic_pass": classify((tmin+tmax)/2)=="VALID",
    }

def _vn01():
    z0,z_match,z_open=120.0,120.0,1e15
    gamma=lambda zl:(zl-z0)/(zl+z0)
    gm,go=gamma(z_match),gamma(z_open)
    return {
        "model_kind":"transmission_line_reflection_coefficient",
        "equation":"Gamma=(Zload-Z0)/(Zload+Z0)",
        "inputs":{"Z0_ohm":z0,"Zmatched_ohm":z_match,"Zopen_proxy_ohm":z_open},
        "observables":{"gamma_matched":q(gm),"gamma_open":q(go)},
        "invariant":"matched termination minimizes first-order reflection magnitude",
        "oracle_pass": abs(gm)<1e-15 and abs(go)>0.999999999,
        "metamorphic_pass": math.isclose(gamma(z0),0.0,abs_tol=1e-15),
    }

def _pf01():
    vin,rtop,rbot,rleak=5.0,100000.0,100000.0,200000.0
    parallel=lambda a,b:1/(1/a+1/b)
    req=parallel(rbot,rleak)
    wet=vin*req/(rtop+req)
    dry=vin*rbot/(rtop+rbot)
    return {
        "model_kind":"resistive_surface_leakage_divider",
        "equation":"Vout=Vin*(Rbottom||Rleak)/(Rtop+(Rbottom||Rleak))",
        "inputs":{"Vin_V":vin,"Rtop_ohm":rtop,"Rbottom_ohm":rbot,"Rleak_ohm":rleak},
        "observables":{"Vout_leaky_V":q(wet),"Vout_dry_V":q(dry)},
        "invariant":"finite leakage to ground depresses the high-impedance divider node",
        "oracle_pass": 0 < wet < dry < vin,
        "metamorphic_pass": math.isclose(dry,vin/2),
    }

def _ie01():
    alpha_delta,threshold=25e-6,0.001
    cold,hot=20.0,90.0
    strain=lambda t:abs(alpha_delta*(t-cold))
    state=lambda t:"OPEN" if strain(t)>threshold else "CLOSED"
    return {
        "model_kind":"thermal_expansion_threshold_state",
        "equation":"joint OPEN iff |DeltaAlpha*(T-Tref)| > strain_threshold",
        "inputs":{"DeltaAlpha_per_K":alpha_delta,"threshold":threshold,"Tref_C":cold,"Thot_C":hot},
        "observables":{"strain_cold":q(strain(cold)),"strain_hot":q(strain(hot)),"state_cold":state(cold),"state_hot":state(hot)},
        "invariant":"thermal excursion crosses a mechanical-open threshold and cooldown restores the state in this reversible PoC",
        "oracle_pass": state(cold)=="CLOSED" and state(hot)=="OPEN",
        "metamorphic_pass": state(cold)=="CLOSED",
    }

def _es01():
    vdiag,rdiag,vext,rext,rload = 5.0,10000.0,12.0,1000.0,20000.0
    def node(vd,ve):
        g=1/rdiag+1/rext+1/rload
        return (vd/rdiag+ve/rext)/g
    both=node(vdiag,vext)
    no_diag=node(0.0,vext)
    no_ext=node(vdiag,0.0)
    return {
        "model_kind":"off_state_backfeed_kcl",
        "equation":"Vnode=(Vdiag/Rdiag+Vext/Rext)/(1/Rdiag+1/Rext+1/Rload)",
        "inputs":{"Vdiag_V":vdiag,"Rdiag_ohm":rdiag,"Vext_V":vext,"Rext_ohm":rext,"Rload_ohm":rload},
        "observables":{"Vnode_both_V":q(both),"Vnode_no_diag_V":q(no_diag),"Vnode_no_ext_V":q(no_ext)},
        "invariant":"external feed keeps the off-state node elevated after diagnostic bias is removed",
        "oracle_pass": no_diag > no_ext and no_diag > 5.0,
        "metamorphic_pass": both > no_diag > 0,
    }

MODELS={"PI01":_pi01,"AS01":_as01,"AP01":_ap01,"DT01":_dt01,"VN01":_vn01,"PF01":_pf01,"IE01":_ie01,"ES01":_es01}

def code_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def build_snapshot():
    rows=[]
    for fid,domain in SELECTED.items():
        result=MODELS[fid]()
        if not result["oracle_pass"] or not result["metamorphic_pass"]:
            raise ValueError("simulation oracle failed: "+fid)
        rows.append({
            "family_id":fid,
            "domain":domain,
            "status":STATUS,
            "mathematical_ground_truth_verified":True,
            "p5_exposure_excluded":False,
            "real_world_representativeness_certified":False,
            "eligible_for_parent_selection":False,
            **result,
        })
    payload={
        "schema_version":1,
        "status":STATUS,
        "acceptance_authorized":False,
        "training_authorized":False,
        "sealed_final_authorized":False,
        "family_count":len(rows),
        "code_sha256":code_sha256(),
        "families":rows,
        "limitations":[
            "Mathematical oracle validity does not prove P5 non-exposure.",
            "Simplified equations/state machines do not certify real-world ECU representativeness.",
            "One deterministic model per domain is a proof-of-concept, not the required 240/240/400 evaluation pools.",
        ],
    }
    payload["snapshot_sha256"]=hashlib.sha256(json.dumps(
        {k:v for k,v in payload.items() if k!="snapshot_sha256"},
        sort_keys=True,ensure_ascii=False,separators=(",",":")
    ).encode()).hexdigest()
    return payload

def validate_snapshot(payload):
    if payload.get("status") != STATUS or payload.get("acceptance_authorized") is not False:
        raise ValueError("simulation snapshot disposition changed")
    if payload.get("training_authorized") is not False or payload.get("sealed_final_authorized") is not False:
        raise ValueError("simulation snapshot cannot authorize training/final")
    rows=payload.get("families")
    if not isinstance(rows,list) or len(rows)!=8:
        raise ValueError("expected eight simulation families")
    if {r.get("family_id") for r in rows} != set(SELECTED):
        raise ValueError("simulation family set changed")
    if {r.get("domain") for r in rows} != set(SELECTED.values()):
        raise ValueError("simulation domain coverage changed")
    if len({r.get("model_kind") for r in rows}) != 8:
        raise ValueError("simulation mechanisms are not unique")
    regenerated=build_snapshot()
    by_id={r["family_id"]:r for r in regenerated["families"]}
    for row in rows:
        expected=by_id[row["family_id"]]
        if row != expected:
            raise ValueError("simulation result mismatch: "+row["family_id"])
        if row["p5_exposure_excluded"] is not False or row["real_world_representativeness_certified"] is not False:
            raise ValueError("unsupported independence/representativeness claim")
        if row["eligible_for_parent_selection"] is not False:
            raise ValueError("quarantined simulation promoted")
    if payload.get("code_sha256") != regenerated["code_sha256"]:
        raise ValueError("simulation code hash mismatch")
    if payload.get("snapshot_sha256") != regenerated["snapshot_sha256"]:
        raise ValueError("simulation snapshot hash mismatch")
    return True

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",default=str(HERE/"simulation_evidence.json"))
    ap.add_argument("--check",action="store_true")
    a=ap.parse_args()
    p=Path(a.output)
    if a.check:
        validate_snapshot(json.loads(p.read_text()))
        print(json.dumps({"status":STATUS,"check":"PASS","families":8,"acceptance_authorized":False}))
        return
    payload=build_snapshot()
    validate_snapshot(payload)
    p.write_text(json.dumps(payload,indent=2,ensure_ascii=False,sort_keys=True)+"\n")
    print(json.dumps({"status":STATUS,"families":8,"output":str(p)}))

if __name__=="__main__":
    main()
