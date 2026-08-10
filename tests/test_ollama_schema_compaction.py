from ai_bridge.ollama.client import compact_schema_for_ollama


def test_compact_schema_preserves_properties_named_title_and_description() -> None:
    schema = {
        "type": "object",
        "title": "Root metadata",
        "properties": {
            "title": {"type": "string", "title": "Field metadata"},
            "description": {"type": "string", "description": "Field metadata"},
        },
        "required": ["title", "description"],
        "additionalProperties": False,
    }

    compact = compact_schema_for_ollama(schema)

    assert "title" not in compact
    assert "title" in compact["properties"]
    assert "description" in compact["properties"]
    assert compact["required"] == ["title", "description"]
