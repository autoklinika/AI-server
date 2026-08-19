from __future__ import annotations

"""Semantic benchmark entrypoint for ventilation prompt v11.7.

This wrapper keeps all v11.6 scenarios and adds regressions found during the
second archived-real-window validation pass.
"""

from copy import deepcopy
from typing import Any

import run_v11_6 as previous

from ai_bridge.adapters.ventilation.analysis_profile_v11_7 import (
    ANALYSIS_THINK,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
)


engine = previous.engine
_legacy_load_scenarios = previous.load_scenarios_v11_6


def load_scenarios_v11_7() -> list[dict[str, Any]]:
    scenarios = deepcopy(_legacy_load_scenarios())

    scenarios.extend(
        [
            {
                "id": "pm_rise_no_causal_story_or_voc_emission_inference",
                "description": (
                    "Real-window regression: setpoint changes must remain control-signal facts; "
                    "the model must not relabel them as ventilation changes, invent causal "
                    "alternatives, or infer VOC emissions from VOC Index."
                ),
                "allowed_status": ["attention"],
                "overrides": {
                    "controller": {
                        "latest_mode": "MANUAL",
                        "mode_counts": {"MANUAL": 180},
                        "setpoints": {
                            "supply_voltage": {
                                "mean": 4.8889,
                                "min": 3.0,
                                "max": 8.0,
                                "first": 8.0,
                                "last": 5.0,
                                "delta": -3.0,
                            },
                            "extract_voltage": {
                                "mean": 5.7222,
                                "min": 3.0,
                                "max": 8.5,
                                "first": 8.5,
                                "last": 6.0,
                                "delta": -2.5,
                            },
                        },
                    },
                    "sensor_bus": {
                        "nodes": {
                            "1": {
                                "readings": {
                                    "pm2_5_ug_m3": {
                                        "count": 180,
                                        "missing": 0,
                                        "mean": 24.715,
                                        "min": 4.3,
                                        "max": 118.1,
                                        "first": 4.4,
                                        "last": 86.6,
                                        "delta": 82.2,
                                        "slope_per_minute": 5.4821,
                                    },
                                    "pm10_0_ug_m3": {
                                        "count": 180,
                                        "missing": 0,
                                        "mean": 44.0656,
                                        "min": 4.9,
                                        "max": 222.7,
                                        "first": 4.9,
                                        "last": 163.4,
                                        "delta": 158.5,
                                        "slope_per_minute": 10.4793,
                                    },
                                    "voc_index": {
                                        "count": 180,
                                        "missing": 0,
                                        "mean": 65.2833,
                                        "min": 20.0,
                                        "max": 127.0,
                                        "first": 80.0,
                                        "last": 32.0,
                                        "delta": -48.0,
                                        "slope_per_minute": -2.9489,
                                    },
                                }
                            },
                            "2": {
                                "readings": {
                                    "pm2_5_ug_m3": {
                                        "count": 180,
                                        "missing": 0,
                                        "mean": 22.3567,
                                        "min": 3.7,
                                        "max": 101.2,
                                        "first": 4.8,
                                        "last": 80.2,
                                        "delta": 75.4,
                                        "slope_per_minute": 4.6566,
                                    },
                                    "pm10_0_ug_m3": {
                                        "count": 180,
                                        "missing": 0,
                                        "mean": 40.0711,
                                        "min": 4.8,
                                        "max": 193.2,
                                        "first": 5.2,
                                        "last": 152.9,
                                        "delta": 147.7,
                                        "slope_per_minute": 9.0858,
                                    },
                                    "voc_index": {
                                        "count": 180,
                                        "missing": 0,
                                        "mean": 73.9667,
                                        "min": 27.0,
                                        "max": 128.0,
                                        "first": 87.0,
                                        "last": 43.0,
                                        "delta": -44.0,
                                        "slope_per_minute": -1.8619,
                                    },
                                }
                            },
                        }
                    },
                },
                "must_match": [
                    {
                        "name": "grounds_pm_rise_endpoints",
                        "field": "analysis_pl",
                        "mode": "all",
                        "patterns": [
                            r"4[.,]9.{0,50}163[.,]4",
                            r"5[.,]2.{0,50}152[.,]9",
                        ],
                    },
                ],
                "must_not_match": [
                    {
                        "name": "does_not_relabel_setpoint_as_ventilation",
                        "field": "analysis_pl",
                        "pattern": r"(?:spadek|wzrost|zmniejszen|zwiększen)[^.!?]{0,45}wentylacj",
                    },
                    {
                        "name": "does_not_invent_reverse_or_third_cause_story",
                        "field": "analysis_pl",
                        "pattern": r"(?:był|była|było|były)\s+(?:skutkiem|przyczyną)|wynik\w*\s+z\s+(?:innej|jakiejś)\s+czynności|inna\s+czynność",
                    },
                    {
                        "name": "does_not_infer_voc_emission_change",
                        "field": "analysis_pl",
                        "pattern": r"wskaz\w*.{0,80}emisj|(?:zmniejsz|spad|wzrost)\w*.{0,50}emisj.{0,80}(?:VOC|lotn)",
                    },
                ],
            },
            {
                "id": "pm_fall_setpoint_channel_identity_and_no_cleaning_story",
                "description": (
                    "Real-window regression: supply/extract identities must not be swapped and "
                    "simultaneous PM/setpoint changes must not become a system-reaction or "
                    "cleaning-process narrative."
                ),
                "allowed_status": ["attention"],
                "overrides": {
                    "controller": {
                        "latest_mode": "MANUAL",
                        "mode_counts": {"MANUAL": 180},
                        "setpoints": {
                            "supply_voltage": {
                                "mean": 3.1944,
                                "min": 2.5,
                                "max": 5.0,
                                "first": 5.0,
                                "last": 2.5,
                                "delta": -2.5,
                            },
                            "extract_voltage": {
                                "mean": 3.1111,
                                "min": 2.0,
                                "max": 6.0,
                                "first": 6.0,
                                "last": 2.0,
                                "delta": -4.0,
                            },
                        },
                    },
                    "sensor_bus": {
                        "nodes": {
                            "1": {
                                "readings": {
                                    "pm10_0_ug_m3": {
                                        "count": 180,
                                        "missing": 0,
                                        "mean": 51.05,
                                        "min": 5.8,
                                        "max": 159.2,
                                        "first": 159.2,
                                        "last": 5.8,
                                        "delta": -153.4,
                                        "slope_per_minute": -9.8933,
                                    },
                                    "voc_index": {
                                        "count": 180,
                                        "missing": 0,
                                        "mean": 59.8667,
                                        "min": 24.0,
                                        "max": 109.0,
                                        "first": 32.0,
                                        "last": 79.0,
                                        "delta": 47.0,
                                        "slope_per_minute": 1.3518,
                                    },
                                }
                            },
                            "2": {
                                "readings": {
                                    "pm10_0_ug_m3": {
                                        "count": 180,
                                        "missing": 0,
                                        "mean": 47.5028,
                                        "min": 5.3,
                                        "max": 149.8,
                                        "first": 149.8,
                                        "last": 5.7,
                                        "delta": -144.1,
                                        "slope_per_minute": -9.0296,
                                    },
                                    "voc_index": {
                                        "count": 180,
                                        "missing": 0,
                                        "mean": 73.6222,
                                        "min": 31.0,
                                        "max": 126.0,
                                        "first": 43.0,
                                        "last": 94.0,
                                        "delta": 51.0,
                                        "slope_per_minute": 2.0598,
                                    },
                                }
                            },
                        }
                    },
                },
                "must_match": [
                    {
                        "name": "keeps_supply_identity",
                        "field": "analysis_pl",
                        "patterns": [
                            r"supply(?:_voltage)?[^.!?]{0,90}5(?:[.,]0)?[^.!?]{0,35}2[.,]5|5(?:[.,]0)?[^.!?]{0,35}2[.,]5[^.!?]{0,90}supply",
                        ],
                    },
                    {
                        "name": "keeps_extract_identity",
                        "field": "analysis_pl",
                        "patterns": [
                            r"extract(?:_voltage)?[^.!?]{0,90}6(?:[.,]0)?[^.!?]{0,35}2(?:[.,]0)?|6(?:[.,]0)?[^.!?]{0,35}2(?:[.,]0)?[^.!?]{0,90}extract",
                        ],
                    },
                    {
                        "name": "keeps_current_voc_endpoints",
                        "field": "analysis_pl",
                        "mode": "all",
                        "patterns": [
                            r"32(?:[.,]0)?.{0,60}79(?:[.,]0)?",
                            r"43(?:[.,]0)?.{0,60}94(?:[.,]0)?",
                        ],
                    },
                ],
                "must_not_match": [
                    {
                        "name": "does_not_invent_system_reaction_or_cleaning",
                        "field": "analysis_pl",
                        "pattern": r"reakcj\w*\s+system|system\w*\s+reakcj|proces\w*\s+oczyszcz|oczyszczan",
                    },
                    {
                        "name": "does_not_relabel_setpoint_as_ventilation",
                        "field": "analysis_pl",
                        "pattern": r"(?:spadek|wzrost|zmniejszen|zwiększen)[^.!?]{0,45}wentylacj",
                    },
                ],
            },
            {
                "id": "non_monotonic_regression_slope_semantics",
                "description": (
                    "Real-window regression: slope_per_minute is a full-window linear-regression "
                    "coefficient, not a final/changing slope; opposite endpoint-delta and slope "
                    "signs must not be narrated as a change of the slope itself."
                ),
                "allowed_status": ["attention", "anomaly"],
                "overrides": {
                    "sensor_bus": {
                        "nodes": {
                            "1": {
                                "readings": {
                                    "voc_index": {
                                        "count": 180,
                                        "missing": 0,
                                        "mean": 234.55,
                                        "min": 24.0,
                                        "max": 416.0,
                                        "first": 24.0,
                                        "last": 140.0,
                                        "delta": 116.0,
                                        "slope_per_minute": -3.279,
                                    }
                                }
                            }
                        }
                    }
                },
                "must_match": [
                    {
                        "name": "uses_non_monotonic_endpoints",
                        "field": "analysis_pl",
                        "mode": "all",
                        "patterns": [r"VOC", r"24(?:[.,]0)?.{0,60}140(?:[.,]0)?"],
                    }
                ],
                "must_not_match": [
                    {
                        "name": "does_not_call_regression_slope_final",
                        "field": "analysis_pl",
                        "pattern": r"(?:ostateczn|końcow)[^.!?]{0,35}(?:nachylen|slope)|(?:nachylen|slope)[^.!?]{0,35}(?:ostateczn|końcow)",
                    },
                    {
                        "name": "does_not_claim_slope_fell_to_regression_value",
                        "field": "analysis_pl",
                        "pattern": r"(?:spad|obniż)\w*[^.!?]{0,35}(?:nachylen|slope)[^.!?]{0,35}-?3[.,]279|(?:nachylen|slope)[^.!?]{0,35}(?:spad|obniż)\w*[^.!?]{0,35}-?3[.,]279",
                    },
                ],
            },
        ]
    )

    return scenarios


engine.PROMPT_VERSION = PROMPT_VERSION
engine.SYSTEM_PROMPT = SYSTEM_PROMPT
engine.ANALYSIS_THINK = ANALYSIS_THINK
engine.load_scenarios = load_scenarios_v11_7


if __name__ == "__main__":
    raise SystemExit(engine.main())
