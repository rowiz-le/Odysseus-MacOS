from src.model_catalog import find_model_metadata, parse_lm_studio_catalog


def test_lm_studio_catalog_uses_loaded_context_and_filters_embeddings():
    parsed = parse_lm_studio_catalog({
        "models": [
            {
                "type": "llm",
                "key": "qwen/qwen3.6-35b-a3b",
                "display_name": "Qwen 3.6",
                "max_context_length": 262144,
                "loaded_instances": [
                    {"config": {"context_length": 65536}},
                ],
                "capabilities": {
                    "reasoning": {
                        "allowed_options": ["off", "on"],
                        "default": "on",
                    },
                    "vision": True,
                    "trained_for_tool_use": True,
                },
            },
            {
                "type": "embedding",
                "key": "text-embedding-model",
                "max_context_length": 2048,
            },
        ],
    })

    model_ids, metadata = parsed
    assert model_ids == ["qwen/qwen3.6-35b-a3b"]
    item = metadata[model_ids[0]]
    assert item["context_length"] == 65536
    assert item["max_context_length"] == 262144
    assert item["loaded"] is True
    assert item["reasoning"]["allowed_options"] == ["off", "on"]
    assert item["vision"] is True
    assert item["supports_tools"] is True


def test_lm_studio_catalog_uses_max_context_when_model_is_unloaded():
    model_ids, metadata = parse_lm_studio_catalog({
        "models": [{
            "type": "llm",
            "key": "google/gemma-4-31b",
            "max_context_length": 262144,
            "loaded_instances": [],
        }],
    })

    assert model_ids == ["google/gemma-4-31b"]
    assert metadata[model_ids[0]]["context_length"] == 262144
    assert metadata[model_ids[0]]["loaded"] is False


def test_find_model_metadata_accepts_model_basename():
    metadata = {
        "publisher/model-name": {"context_length": 131072},
    }
    assert find_model_metadata(metadata, "model-name")["context_length"] == 131072


def test_non_lm_studio_schema_is_rejected():
    assert parse_lm_studio_catalog({"data": [{"id": "gpt-4o"}]}) is None
