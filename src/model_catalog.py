"""Normalized model metadata discovery for local model servers."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse, urlunparse

import httpx


_REASONING_OPTIONS = {"off", "on", "low", "medium", "high"}


def _server_root(base_url: str) -> str:
    parsed = urlparse((base_url or "").strip())
    path = (parsed.path or "").rstrip("/")
    for suffix in (
        "/v1/chat/completions",
        "/chat/completions",
        "/api/v1/chat",
        "/api/v1/models",
        "/v1/models",
        "/models",
        "/v1",
    ):
        if path.endswith(suffix):
            path = path[: -len(suffix)].rstrip("/")
            break
    return urlunparse(parsed._replace(path=path, params="", query="", fragment="")).rstrip("/")


def _ollama_api_root(base_url: str) -> Optional[str]:
    parsed = urlparse((base_url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").rstrip("/")
    looks_ollama = (
        parsed.port == 11434
        or host == "ollama.com"
        or host.endswith(".ollama.com")
        or "ollama" in host
    )
    if not looks_ollama:
        return None
    for suffix in (
        "/api/chat",
        "/api/tags",
        "/api/generate",
        "/v1/chat/completions",
        "/v1/models",
        "/chat/completions",
        "/models",
        "/v1",
    ):
        if path.endswith(suffix):
            path = path[: -len(suffix)].rstrip("/")
            break
    if path.endswith("/api"):
        return urlunparse(parsed._replace(path=path, params="", query="", fragment="")).rstrip("/")
    root = urlunparse(parsed._replace(path=path, params="", query="", fragment="")).rstrip("/")
    return root.rstrip("/") + "/api"


def _positive_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _reasoning_metadata(capabilities: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(capabilities, dict):
        return None
    reasoning = capabilities.get("reasoning")
    if not isinstance(reasoning, dict):
        return None
    allowed = [
        str(option).strip().lower()
        for option in reasoning.get("allowed_options", [])
        if str(option).strip().lower() in _REASONING_OPTIONS
    ]
    default = str(reasoning.get("default") or "").strip().lower()
    if default not in _REASONING_OPTIONS:
        default = allowed[0] if allowed else ""
    if not allowed and not default:
        return None
    return {"allowed_options": allowed, "default": default}


def parse_lm_studio_catalog(data: Any) -> Optional[Tuple[list[str], Dict[str, Dict[str, Any]]]]:
    """Parse LM Studio's native ``GET /api/v1/models`` response.

    Returns None when the response is not the LM Studio v1 schema. Embedding
    models are deliberately excluded from the chat model list.
    """
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        return None

    model_ids: list[str] = []
    metadata: Dict[str, Dict[str, Any]] = {}
    for raw in data["models"]:
        if not isinstance(raw, dict) or raw.get("type") != "llm":
            continue
        model_id = str(raw.get("key") or "").strip()
        if not model_id:
            continue

        loaded_contexts = []
        for instance in raw.get("loaded_instances") or []:
            if not isinstance(instance, dict):
                continue
            config = instance.get("config") or {}
            if isinstance(config, dict):
                context = _positive_int(config.get("context_length"))
                if context:
                    loaded_contexts.append(context)

        max_context = _positive_int(raw.get("max_context_length"))
        effective_context = max(loaded_contexts) if loaded_contexts else max_context
        capabilities = raw.get("capabilities") if isinstance(raw.get("capabilities"), dict) else {}
        item = {
            "id": model_id,
            "display_name": str(raw.get("display_name") or model_id.split("/")[-1]),
            "type": "llm",
            "publisher": str(raw.get("publisher") or ""),
            "architecture": str(raw.get("architecture") or ""),
            "format": str(raw.get("format") or ""),
            "context_length": effective_context,
            "max_context_length": max_context,
            "loaded": bool(loaded_contexts),
            "vision": bool(capabilities.get("vision")),
            "supports_tools": bool(capabilities.get("trained_for_tool_use")),
        }
        reasoning = _reasoning_metadata(capabilities)
        if reasoning:
            item["reasoning"] = reasoning

        model_ids.append(model_id)
        metadata[model_id] = item

    return model_ids, metadata


def parse_ollama_catalog(data: Any) -> Optional[Tuple[list[str], Dict[str, Dict[str, Any]]]]:
    """Parse Ollama's native ``GET /api/tags`` response.

    A valid Ollama server may return an empty ``models`` list, so ``([], {})``
    means reachable-but-empty, while ``None`` means "not an Ollama catalog".
    """
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        return None

    model_ids: list[str] = []
    metadata: Dict[str, Dict[str, Any]] = {}
    for raw in data["models"]:
        if not isinstance(raw, dict):
            continue
        model_id = str(raw.get("name") or raw.get("model") or raw.get("id") or "").strip()
        if not model_id:
            continue
        details = raw.get("details") if isinstance(raw.get("details"), dict) else {}
        item: Dict[str, Any] = {
            "id": model_id,
            "display_name": model_id,
            "provider": "ollama",
        }
        for key in ("modified_at", "digest"):
            if raw.get(key):
                item[key] = raw.get(key)
        size = _positive_int(raw.get("size"))
        if size:
            item["size"] = size
        for key in ("family", "format", "parameter_size", "quantization_level"):
            if details.get(key):
                item[key] = str(details.get(key))
        if ":cloud" in model_id.lower() or raw.get("cloud"):
            item["cloud"] = True

        model_ids.append(model_id)
        metadata[model_id] = item

    return model_ids, metadata


def parse_standard_model_catalog(
    data: Any,
) -> Optional[Tuple[list[str], Dict[str, Dict[str, Any]]]]:
    """Parse OpenAI/Anthropic-style model lists and retain useful limits."""
    if not isinstance(data, dict):
        return None
    raw_models = data.get("data")
    if not isinstance(raw_models, list):
        raw_models = data.get("models")
    if not isinstance(raw_models, list):
        return None

    model_ids: list[str] = []
    metadata: Dict[str, Dict[str, Any]] = {}
    context_fields = (
        "context_length",
        "context_window",
        "max_context_length",
        "max_model_len",
        "max_seq_len",
        "max_input_tokens",
        "input_token_limit",
    )
    for raw in raw_models:
        if not isinstance(raw, dict):
            continue
        model_id = str(raw.get("id") or raw.get("name") or raw.get("model") or "").strip()
        if not model_id:
            continue

        context = None
        for field in context_fields:
            context = _positive_int(raw.get(field))
            if context:
                break
        if context is None:
            for block_name in ("meta", "model_extra", "capabilities", "limits"):
                block = raw.get(block_name)
                if not isinstance(block, dict):
                    continue
                for field in context_fields:
                    context = _positive_int(block.get(field))
                    if context:
                        break
                if context:
                    break

        item: Dict[str, Any] = {
            "id": model_id,
            "display_name": str(raw.get("display_name") or raw.get("displayName") or model_id.split("/")[-1]),
        }
        if context:
            item["context_length"] = context
        max_output = _positive_int(raw.get("max_output_tokens") or raw.get("output_token_limit"))
        if max_output:
            item["max_output_tokens"] = max_output
        model_ids.append(model_id)
        metadata[model_id] = item

    return (model_ids, metadata) if model_ids else None


def fetch_lm_studio_catalog(
    base_url: str,
    api_key: Optional[str] = None,
    *,
    timeout: float = 3.0,
) -> Optional[Tuple[list[str], Dict[str, Dict[str, Any]]]]:
    """Return normalized LM Studio models, or None for non-LM-Studio servers."""
    root = _server_root(base_url)
    if not root:
        return None
    parsed = urlparse(root)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    if parsed.port != 1234 and "lmstudio" not in host and "lm-studio" not in host and "lmstudio" not in path:
        return None
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = httpx.get(
            f"{root}/api/v1/models",
            headers=headers,
            timeout=timeout,
        )
        if not response.is_success:
            return None
        return parse_lm_studio_catalog(response.json())
    except Exception:
        return None


def fetch_ollama_catalog(
    base_url: str,
    api_key: Optional[str] = None,
    *,
    timeout: float = 3.0,
) -> Optional[Tuple[list[str], Dict[str, Dict[str, Any]]]]:
    """Return normalized Ollama models, or None for non-Ollama endpoints."""
    root = _ollama_api_root(base_url)
    if not root:
        return None
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = httpx.get(f"{root}/tags", headers=headers, timeout=timeout)
        if not response.is_success:
            return None
        return parse_ollama_catalog(response.json())
    except Exception:
        return None


def find_model_metadata(metadata: Any, model: str) -> Optional[Dict[str, Any]]:
    """Find metadata by exact ID or basename, tolerating JSON-decoded dicts."""
    if not isinstance(metadata, dict) or not model:
        return None
    if isinstance(metadata.get(model), dict):
        return metadata[model]
    basename = model.rstrip("/").split("/")[-1]
    for model_id, item in metadata.items():
        if str(model_id).rstrip("/").split("/")[-1] == basename and isinstance(item, dict):
            return item
    return None
