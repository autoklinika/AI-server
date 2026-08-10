from ai_bridge.analysis.schemas import VentilationAnalysisResult
from ai_bridge.ollama.client import compact_schema_for_ollama


def test_compact_schema_preserves_domain_title_and_description_properties() -> None:
    compact = compact_schema_for_ollama(VentilationAnalysisResult.model_json_schema())

    observation = compact["properties"]["observations"]["items"]
    assert "title" in observation["properties"]
    assert "title" in observation["required"]

    anomaly = compact["properties"]["anomalies"]["items"]
    assert "title" in anomaly["properties"]
    assert "title" in anomaly["required"]
    assert "description" in anomaly["properties"]
    assert "description" in anomaly["required"]
