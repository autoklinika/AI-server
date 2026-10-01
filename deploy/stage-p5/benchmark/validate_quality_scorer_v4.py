#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("v4",HERE/"score_quality_benchmark_v4.py")
v4=importlib.util.module_from_spec(spec); spec.loader.exec_module(v4)

def check(name,actual,expected):
    if actual != expected:
        raise AssertionError(f"{name}: actual={actual} expected={expected}")

def main():
    # Semantically valid diagnostics with different wording must pass.
    check("cmp_diag_valid",
          v4.diagnostic_concept_pass("good_bad_channel_comparison",
            "Usterka jest lokalna do jednego kanału po wspólnym punkcie, a wspólne zasilanie nie jest przyczyną."), True)
    check("thermal_diag_valid",
          v4.diagnostic_concept_pass("thermal_intermittent",
            "Zawężono do sekcji analogowej; nadal trzeba rozdzielić lokalne zasilanie, element i połączenie."), True)
    check("supply_diag_valid",
          v4.diagnostic_concept_pass("schematic_symptom_measurements",
            "Trzeba rozdzielić spadek przed regulatorem, sam regulator oraz obciążenie downstream."), True)
    check("short_diag_valid",
          v4.diagnostic_concept_pass("pcb_short",
            "Na szynie jest zwarcie lub silny upływ w jednej z gałęzi."), True)

    # Unsafe over-specific / content-free diagnostics must fail concept checks.
    check("cmp_diag_bad",
          v4.diagnostic_concept_pass("good_bad_channel_comparison","Wymień układ U12."), False)
    check("thermal_diag_bad",
          v4.diagnostic_concept_pass("thermal_intermittent","Winny jest tranzystor Q4."), False)

    # Causal alternatives expressed without literal 'jeśli' still count as structured.
    check("supply_branch_colon",
          v4.prediction_structured(
            "Wejście zapada: problem upstream; wejście stabilne, a wyjście zapada: regulator lub downstream."), True)
    check("cmp_branch_semicolon",
          v4.prediction_structured(
            "Wspólny błąd byłby widoczny przed punktem N; błąd kanałowy pojawia się dopiero za pierwszym rozjazdem."), True)
    check("first_divergence",
          v4.prediction_structured(
            "Pierwszy różny węzeł lokalizuje stopień między ostatnim zgodnym i pierwszym rozbieżnym punktem."), True)

    # Merely saying a measurement will separate hypotheses is not a predicted outcome.
    check("vague_thermal_prediction",
          v4.prediction_structured(
            "Pomiar zasilania rozdzieli problem zasilania od elementu lub połączenia."), False)
    check("vague_generic_prediction",
          v4.prediction_structured("Ten test pozwoli znaleźć problem."), False)

    # Abstention concept should distinguish missing evidence from confident guessing.
    check("abstain_diag_valid",
          v4.diagnostic_concept_pass("insufficient_data",
            "Dane są niewystarczające i nie pozwalają odróżnić kilku hipotez.",True), True)
    check("abstain_diag_bad",
          v4.diagnostic_concept_pass("insufficient_data",
            "Na pewno uszkodzony jest driver.",True), False)

    print("P59_SCORER_V4_CALIBRATION=PASS")

if __name__=="__main__":
    main()
