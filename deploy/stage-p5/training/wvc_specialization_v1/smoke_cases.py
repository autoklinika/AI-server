"""Disjoint WVC smoke cases. Never training eligible."""
from __future__ import annotations
import json

SYSTEM = (
    "Jesteś analitykiem technicznym WVC. Oddziel obserwacje od hipotez, "
    "nie utożsamiaj komendy z wykonaniem ani korelacji z przyczyną. "
    "Wskaż najbardziej rozstrzygające następne sprawdzenie i brakujące dane."
)

CASES = [
    ("SMOKE-01-validity",
     {"nodes":{"1":{"online":True,"valid":False,"stale":True,"pm2_5":88.0,"errors":4},
               "2":{"online":True,"valid":True,"stale":False,"pm2_5":6.1,"errors":0}}},
     "Jeden kanał pokazuje duży PM, ale jego flaga valid jest fałszywa i dane są stale. Jak to interpretować?",
     ["ważność","stale","najpierw jakość danych"], ["uszkodzony czujnik"]),
    ("SMOKE-02-command",
     {"mode":"MANUAL","setpoint_v":{"supply":9.2,"extract":9.0},"rpm":None,"airflow":None,"output_state_known":True},
     "Czy wysokie napięcia zadane dowodzą, że wentylatory faktycznie pracują z dużą wydajnością?",
     ["komenda","wykonanie","RPM"], ["wysoki przepływ"]),
    ("SMOKE-03-feedback",
     {"setpoint_v":{"supply":6.0,"extract":6.0},"tacho":{"supply":420,"extract":1210,"valid":True},"current_a":{"supply":0.31,"extract":0.72}},
     "Oba kanały mają tę samą komendę, ale feedback bardzo się różni. Jaki test najlepiej rozdzieli pomiar od wykonania?",
     ["feedback","kanał","porównaj"], ["sterownik jest uszkodzony"]),
    ("SMOKE-04-peer",
     {"nodes":{"1":{"valid":True,"pm2_5":54.0,"voc_index":210},"2":{"valid":True,"pm2_5":52.0,"voc_index":205}},
      "placement_known":False,"process_state":"unknown"},
     "Dwa sprawne sensory zmieniły się podobnie. Co to mówi o wspólnym zdarzeniu, a czego nadal nie wiemy?",
     ["oba","wspólne","źródło"], ["na pewno proces"]),
    ("SMOKE-05-bus",
     {"sensor_bus":{"ready_ratio":0.38,"worker_alive_ratio":0.44,"restarts":3},
      "node":{"online_ratio":0.41,"stale_ratio":0.47,"communication_errors":11}},
     "W tym oknie odczyty znikają i wracają. Czy analizować wartości środowiskowe, czy najpierw jakość magistrali?",
     ["komunikacja","stale","najpierw"], ["sensor do wymiany"]),
    ("SMOKE-06-sequence",
     {"events":[{"t":"08:00:00","mode":"MANUAL","ready":True,"alarm":None},
                {"t":"08:00:08","mode":"MANUAL","ready":False,"alarm":"DAC_COMMUNICATION_LOST"},
                {"t":"08:00:15","mode":"FAULT","ready":False,"alarm":"HARDWARE_NOT_READY"}]},
     "Który fakt w kolejności zdarzeń jest najbardziej użyteczny do zawężenia przyczyny?",
     ["kolejność","gotowość","przed"], ["FAULT jest przyczyną"]),
    ("SMOKE-07-causality",
     {"periods":[{"setpoint":8.0,"pm10":12.0},{"setpoint":4.0,"pm10":91.0}],
      "rpm":None,"airflow":None,"process_state":"unknown"},
     "Po obniżeniu setpointu PM10 wzrosło. Czy można uznać, że obniżenie nastawy spowodowało wzrost?",
     ["korelacja","wykonanie","proces"], ["spowodowało na pewno"]),
    ("SMOKE-08-alarm",
     {"active_alarm":"AERO_BUS_UNAVAILABLE","sensor_bus_ready":True,"sensor_errors":0,"actuator_feedback":None},
     "Alarm AERO jest aktywny, a sensory raportują poprawnie. Czy z tego wynika zacięta przepustnica?",
     ["alarm","warstwa","feedback"], ["zacięta przepustnica"]),
    ("SMOKE-09-baseline",
     {"pm2_5":18.0,"voc_index":142,"historical_baseline":None,"accepted_thresholds":None},
     "Czy te wartości są prawidłowe i bezpieczne dla tej instalacji?",
     ["baseline","próg","nie można"], ["bezpieczne"]),
    ("SMOKE-10-index",
     {"voc_index":{"first":71,"last":190},"nox_index":{"first":3,"last":4},"pm2_5":{"first":5.0,"last":5.3}},
     "VOC Index wzrósł, ale PM i NOx Index są stabilne. Czy mogę nazwać to wzrostem stężenia VOC?",
     ["indeks","stężenie","nie"], ["stężenie wynosi"]),
    ("SMOKE-11-domain",
     {"mode":"MANUAL","sensor_bus_ready":True,"setpoint_v":5.5,"rpm":None,"airflow":None},
     "Ktoś proponuje od razu diagnozować CAN, ECU i MOSFET. Czy telemetria WVC uzasadnia ten kierunek?",
     ["WVC","topologia","najpierw"], ["CAN jest uszkodzony"]),
    ("SMOKE-12-recovery",
     {"events":[{"t":"09:10:00","ready":False,"alarm":"BUS_TIMEOUT"},
                {"t":"09:10:20","action":"restart_worker"},
                {"t":"09:10:25","ready":True,"alarm":None}]},
     "Po restarcie wszystko wróciło. Czy restart potwierdza przyczynę problemu?",
     ["restart","nie identyfikuje","przed"], ["restart dowodzi"]),
]

def smoke_records():
    rows=[]
    for cid,ctx,q,must,must_not in CASES:
        rows.append({
            "record_id":"P513-"+cid,
            "system":SYSTEM,
            "user":q+" Telemetria JSON: "+json.dumps(ctx,ensure_ascii=False,sort_keys=True,separators=(",",":")),
            "metadata":{"category":cid.split("-",2)[-1],"split":"smoke","training_eligible":False,
                        "language":"pl","source_kind":"project_owned_synthetic_holdout"},
            "expected":{"must_include":must,"must_not_include":must_not},
        })
    return rows
