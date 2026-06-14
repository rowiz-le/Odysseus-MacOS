"""
model_context.py

Query and cache model context window sizes from OpenAI-compatible APIs.
Provides token estimation for context usage tracking.
"""

import logging
import json
import sys
from typing import Any, Dict, List, Optional, Tuple

from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal"}
_PRIVATE_PREFIXES = ("10.", "172.16.", "172.17.", "172.18.", "172.19.",
                     "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                     "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
                     "172.30.", "172.31.", "192.168.", "100.")


def _normalize_base_for_compare(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    for suffix in ("/chat/completions", "/models", "/completions", "/v1/messages"):
        if url.endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
    return url


def _configured_endpoint_kind(url: str) -> Optional[str]:
    """Return configured endpoint kind for a chat/base URL when available."""
    target = _normalize_base_for_compare(url)
    if not target:
        return None
    if "core.database" not in sys.modules:
        return None
    try:
        from core.database import SessionLocal, ModelEndpoint
        db = SessionLocal()
        try:
            rows = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).all()
            for ep in rows:
                base = _normalize_base_for_compare(getattr(ep, "base_url", "") or "")
                if not base:
                    continue
                if target != base and not target.startswith(base + "/"):
                    continue
                kind = (getattr(ep, "endpoint_kind", None) or "auto").strip().lower()
                if kind in ("local", "api", "proxy"):
                    return kind
                if getattr(ep, "api_key", None):
                    parsed = urlparse(base)
                    host = (parsed.hostname or "").lower()
                    path = (parsed.path or "").rstrip("/")
                    if parsed.port != 11434 and "ollama" not in host and (path.endswith("/v1") or "/openai" in path):
                        return "proxy"
                return "auto"
        finally:
            db.close()
    except Exception:
        return None


def _configured_model_context(url: str, model: str) -> Optional[int]:
    """Read persisted per-model context metadata for a configured endpoint."""
    target = _normalize_base_for_compare(url)
    if not target or not model or "core.database" not in sys.modules:
        return None
    try:
        from core.database import SessionLocal, ModelEndpoint
        from src.model_catalog import find_model_metadata

        db = SessionLocal()
        try:
            rows = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).all()
            for ep in rows:
                base = _normalize_base_for_compare(getattr(ep, "base_url", "") or "")
                if target != base and not target.startswith(base + "/"):
                    continue
                raw = getattr(ep, "model_metadata", None)
                if not raw:
                    return None
                metadata = json.loads(raw) if isinstance(raw, str) else raw
                item = find_model_metadata(metadata, model)
                if not item:
                    return None
                for field in (
                    "context_length",
                    "context_window",
                    "max_context_length",
                    "max_input_tokens",
                    "input_token_limit",
                ):
                    value = item.get(field)
                    if isinstance(value, (int, float)) and value > 0:
                        return int(value)
                return None
        finally:
            db.close()
    except Exception:
        return None
    return None


def _is_local_endpoint(url: str) -> bool:
    """Check if URL points to a local/private/tailscale address."""
    kind = _configured_endpoint_kind(url)
    if kind in ("api", "proxy"):
        return False
    if kind == "local":
        return True
    try:
        host = urlparse(url).hostname or ""
        return host in _LOCAL_HOSTS or host.startswith(_PRIVATE_PREFIXES)
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_CONTEXT = 128000
REQUEST_TIMEOUT = 5

# Known context windows for major API models (used as fallback when /models
# endpoint doesn't report context_length).
# Substring matching — use the shortest unique prefix so variants get caught.
KNOWN_CONTEXT_WINDOWS = {
    # --- Anthropic ---
    'claude-opus-4-8': 1000000,
    'claude-opus-4.8': 1000000,
    'claude-opus-4-7': 1000000,
    'claude-opus-4.7': 1000000,
    'claude-opus-4-6': 1000000,
    'claude-opus-4.6': 1000000,
    'claude-sonnet-4-6': 1000000,
    'claude-sonnet-4.6': 1000000,
    'claude-sonnet-4-5': 200000,
    'claude-sonnet-4': 200000,
    'claude-opus-4': 200000,
    'claude-haiku-4': 200000,
    'claude-haiku-3-5': 200000,
    'claude-3-5-sonnet': 200000,
    'claude-3-5-haiku': 200000,
    'claude-3-opus': 200000,
    'claude-3-sonnet': 200000,
    'claude-3-haiku': 200000,

    # --- OpenAI ---
    'gpt-5.5': 1050000,
    'gpt-5.4': 1050000,
    'gpt-5.2': 400000,
    'gpt-5': 400000,
    'gpt-4.1': 1047576,
    'gpt-4.1-mini': 1047576,
    'gpt-4.1-nano': 1047576,
    'gpt-4o': 128000,
    'gpt-4o-mini': 128000,
    'gpt-4-turbo': 128000,
    'gpt-4': 8192,
    'gpt-3.5-turbo': 16385,
    'o1': 200000,
    'o1-mini': 128000,
    'o1-pro': 200000,
    'o3': 200000,
    'o3-mini': 200000,
    'o4-mini': 200000,

    # --- DeepSeek ---
    'deepseek-v4': 1000000,
    'deepseek-chat': 64000,
    'deepseek-coder': 64000,
    'deepseek-reasoner': 64000,
    'deepseek-r1': 64000,
    'deepseek-v3': 64000,
    'deepseek-v2': 64000,

    # --- Google ---
    'gemini-3.5': 1048576,
    'gemini-3.1': 1048576,
    'gemini-3': 1048576,
    'gemini-2.5-pro': 1048576,
    'gemini-2.5-flash': 1048576,
    'gemini-2.0-flash': 1048576,
    'gemini-1.5-pro': 1048576,
    'gemini-1.5-flash': 1048576,
    'gemma-4': 262144,
    'gemma-3': 128000,
    'gemma-2': 8192,

    # --- Mistral ---
    'mistral-large': 128000,
    'mistral-medium': 32000,
    'mistral-small': 32000,
    'mistral-nemo': 128000,
    'mistral-7b': 32000,
    'mixtral': 32000,
    'codestral': 32000,
    'pixtral': 128000,

    # --- xAI ---
    'grok-4': 131072,
    'grok-3': 131072,
    'grok-2': 131072,

    # --- Meta / Llama ---
    'llama-4': 1048576,
    'llama-3.3': 131072,
    'llama-3.2': 131072,
    'llama-3.1': 131072,
    'llama-3': 131072,

    # --- Qwen ---
    'qwen3': 131072,
    'qwen2.5': 131072,
    'qwen2': 32768,
    'qwq': 32768,

    # --- Cohere ---
    'command-r-plus': 128000,
    'command-r': 128000,
    'command-a': 256000,

    # --- Perplexity ---
    'sonar-pro': 200000,
    'sonar': 128000,

    # --- MiniMax ---
    'minimax': 1000000,

    # --- Moonshot / Kimi ---
    'moonshot': 128000,
    'kimi': 128000,

    # --- Microsoft ---
    'phi-4': 16000,
    'phi-3': 128000,

    # --- Nvidia ---
    'nemotron': 131072,

    # --- Yi ---
    'yi-large': 32768,
    'yi-1.5': 16384,

    # --- 01.ai ---
    'yi-lightning': 16384,

    # --- Nous ---
    'hermes': 131072,
    'nous-hermes': 131072,

    # --- Open community ---
    'dolphin': 32768,
    'mythomax': 4096,
    'wizard': 32768,
    'openchat': 8192,
    'solar': 32768,
}

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
_context_cache: Dict[Tuple[str, str], int] = {}


CONTEXT_METADATA_FIELDS = (
    "context_length",
    "context_window",
    "max_context_length",
    "max_input_tokens",
    "input_token_limit",
)

from typing import Optional

def clear_context_cache(endpoint_url: Optional[str] = None, model: Optional[str] = None) -> None:
    """Clear cached context-window lookups after model metadata changes."""
    if endpoint_url is None and model is None:
        _context_cache.clear()
        return
    for key in list(_context_cache.keys()):
        key_url, key_model = key
        if endpoint_url is not None and key_url != endpoint_url:
            continue
        if model is not None and key_model != model:
            continue
        _context_cache.pop(key, None)


def metadata_context_length(metadata: Any) -> Optional[int]:
    """Extract a positive context window from a model metadata item."""
    if not isinstance(metadata, dict):
        return None
    for field in CONTEXT_METADATA_FIELDS:
        value = metadata.get(field)
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
        if isinstance(value, str):
            try:
                parsed = int(value.strip())
            except ValueError:
                continue
            if parsed > 0:
                return parsed
    return None


def get_context_length(endpoint_url: str, model: str) -> int:
    """Get the context window size for a model.

    Queries /v1/models on the endpoint and looks for context_length
    or context_window fields. Caches result per (endpoint, model).
    Falls back to DEFAULT_CONTEXT if unavailable.
    """
    configured_kind = _configured_endpoint_kind(endpoint_url)
    is_local = _is_local_endpoint(endpoint_url)
    # Key on (endpoint_url, model): the same model id can be served by two
    # different remote endpoints with different real context windows (e.g. a
    # capped proxy vs. the full provider), so caching by model id alone would
    # serve one endpoint's window for the other (issue #2603).
    cache_key = (endpoint_url, model)
    if not is_local and cache_key in _context_cache:
        return _context_cache[cache_key]

    ctx = _query_context_length(endpoint_url, model)
    # Only cache non-default values to allow retry on next request.
    # Local endpoints can restart with a different --max-model-len while keeping
    # the same model id, so always re-query them instead of serving stale cache.
    if not is_local and (ctx != DEFAULT_CONTEXT or configured_kind in ("api", "proxy")):
        _context_cache[cache_key] = ctx
    logger.info(f"Context length for {model}: {ctx}")
    return ctx


def _lookup_known(model: str) -> Optional[int]:
    """Check known context windows by substring match.

    Picks the LONGEST matching key so a short key never shadows a more specific
    one. Without this, 'o1' (200k) precedes 'o1-mini' (128k) in the table and a
    first-match return would report o1-mini's window as 200k.
    """
    name = model.lower()
    basename = name.split("/")[-1] if "/" in name else name
    basename = basename.split(":")[0]  # strip :free, :extended etc.
    best_key: Optional[str] = None
    best_ctx: Optional[int] = None
    for key, ctx in KNOWN_CONTEXT_WINDOWS.items():
        if key in basename or key in name:
            if best_key is None or len(key) > len(best_key):
                best_key, best_ctx = key, ctx
    return best_ctx


def context_window_hint(endpoint_url: str, model: str, metadata: Any = None) -> Dict[str, Any]:
    """Return a user-facing context-window recommendation for one model."""
    item = metadata if isinstance(metadata, dict) else {}
    known = _apply_provider_context_limit(endpoint_url, model, _lookup_known(model))
    max_context = None
    for field in ("max_context_length", "max_model_len", "max_seq_len"):
        value = item.get(field)
        if isinstance(value, (int, float)) and value > 0:
            max_context = int(value)
            break
    detected = None
    if item.get("context_user_override"):
        detected = metadata_context_length({"context_length": item.get("context_detected_length")})
    if not detected:
        detected = metadata_context_length(item) if not item.get("context_user_override") else None

    if known:
        suggested = known
        source = "known"
    elif max_context:
        suggested = max_context
        source = "server_max"
    elif detected:
        suggested = detected
        source = "server"
    else:
        suggested = DEFAULT_CONTEXT
        source = "fallback"

    return {
        "suggested_context_length": suggested,
        "suggestion_source": source,
        "known_context_length": known,
        "detected_context_length": detected,
        "max_context_length": max_context,
    }


def context_window_warnings(
    endpoint_url: str,
    model: str,
    context_length: Optional[int],
    metadata: Any = None,
) -> list[Dict[str, str]]:
    """Explain likely risks for a user-edited context window."""
    if not context_length:
        return [{"level": "warning", "message": "No context window is saved; Odysseus will fall back to auto-detection."}]
    hint = context_window_hint(endpoint_url, model, metadata)
    suggested = int(hint.get("suggested_context_length") or 0)
    max_context = int(hint.get("max_context_length") or 0)
    warnings: list[Dict[str, str]] = []
    if context_length < 4096:
        warnings.append({"level": "danger", "message": "Very small context windows can break normal chat history and tool output."})
    if suggested:
        if context_length > int(suggested * 1.05):
            warnings.append({"level": "danger", "message": "Above the recommended context. The provider or server may reject long prompts."})
        elif context_length < int(suggested * 0.5):
            warnings.append({"level": "warning", "message": "Less than half of the recommended context. Compaction will trigger much earlier than needed."})
        elif context_length < suggested:
            warnings.append({"level": "info", "message": "Below the recommendation. This is safe, but Odysseus will compact earlier."})
    if max_context and _is_local_endpoint(endpoint_url) and context_length > max_context:
        warnings.append({"level": "warning", "message": "Above the local server's reported max. Restart the model server with a larger context if you want this to work."})
    return warnings


def describe_context_window(endpoint_url: str, model: str, metadata: Any = None) -> Dict[str, Any]:
    """Build the context payload shown in Settings > Add Models."""
    item = metadata if isinstance(metadata, dict) else {}
    hint = context_window_hint(endpoint_url, model, item)
    current = metadata_context_length(item) or hint["suggested_context_length"]
    return {
        **hint,
        "context_length": current,
        "context_user_override": bool(item.get("context_user_override")),
        "context_source": item.get("context_source") or hint["suggestion_source"],
        "warnings": context_window_warnings(endpoint_url, model, current, item),
    }


def _apply_provider_context_limit(
    endpoint_url: str,
    model: str,
    context_length: Optional[int],
) -> Optional[int]:
    """Apply documented provider-specific limits to an otherwise known model.

    Claude Opus 4.8 supports a 1M-token window on the Claude API, Amazon
    Bedrock, and Vertex AI, while Microsoft Foundry currently caps it at 200K.
    OpenAI-compatible gateways with no provider-identifying hostname retain the
    model's normal limit.
    """
    if not context_length:
        return context_length
    try:
        host = (urlparse(endpoint_url).hostname or "").lower()
    except Exception:
        host = ""
    normalized = (model or "").lower().replace(".", "-").replace("_", "-")
    is_foundry = (
        host.endswith(".azure.com")
        or host.endswith(".azure.us")
        or host.endswith(".microsoft.com")
    )
    if is_foundry and "claude-opus-4-8" in normalized:
        return min(int(context_length), 200000)
    return int(context_length)


def _query_context_length(endpoint_url: str, model: str) -> int:
    """Query the model API for context length."""
    known = _lookup_known(model)
    api_ctx = None
    configured_kind = _configured_endpoint_kind(endpoint_url)
    configured_context = _configured_model_context(endpoint_url, model)
    if configured_context:
        logger.info(f"Using configured model metadata for {model}: {configured_context}")
        return _apply_provider_context_limit(endpoint_url, model, configured_context)

    # Large OpenAI-compatible proxies can make /models expensive. If the
    # endpoint is explicitly configured as API/proxy, prefer known context
    # metadata (or the default) over downloading the full catalog.
    if configured_kind in ("api", "proxy"):
        if known:
            logger.info(f"Using known context window for {model}: {known}")
            return _apply_provider_context_limit(endpoint_url, model, known)
        return DEFAULT_CONTEXT

    # Try llama.cpp /slots endpoint first — reports actual serving context
    if _is_local_endpoint(endpoint_url):
        try:
            from src.model_catalog import fetch_lm_studio_catalog, find_model_metadata

            catalog = fetch_lm_studio_catalog(endpoint_url, timeout=REQUEST_TIMEOUT)
            if catalog is not None:
                _, metadata = catalog
                item = find_model_metadata(metadata, model)
                if item:
                    value = item.get("context_length") or item.get("max_context_length")
                    if isinstance(value, (int, float)) and value > 0:
                        return int(value)
        except Exception:
            pass
        try:
            base = endpoint_url.split("/v1")[0] if "/v1" in endpoint_url else endpoint_url.rsplit("/", 1)[0]
            r = httpx.get(f"{base}/slots", timeout=REQUEST_TIMEOUT)
            if r.is_success:
                slots = r.json()
                if isinstance(slots, list) and slots:
                    n_ctx = slots[0].get("n_ctx")
                    if n_ctx and isinstance(n_ctx, int) and n_ctx > 0:
                        logger.info(f"llama.cpp /slots reports n_ctx={n_ctx} for {model}")
                        return n_ctx
        except Exception:
            pass

    # GitHub Copilot's /models requires auth + X-GitHub-Api-Version headers that
    # aren't available here; an unauthenticated probe just 400s. All Copilot
    # picker models are major API models covered by the known-context table, so
    # rely on that instead of a doomed network call.
    from src.copilot import is_copilot_base
    if is_copilot_base(endpoint_url):
        if known:
            logger.info(f"Using known context window for {model}: {known}")
        return known or DEFAULT_CONTEXT

    models_url = endpoint_url.replace("/chat/completions", "/models")
    try:
        r = httpx.get(models_url, timeout=REQUEST_TIMEOUT)
        if r.is_success:
            data = r.json()
            models_list = data.get("data") or []

            for m in models_list:
                mid = m.get("id", "")
                if mid == model or mid.split("/")[-1] == model.split("/")[-1]:
                    for field in (
                        "context_length",
                        "context_window",
                        "max_model_len",
                        "max_context_length",
                        "max_seq_len",
                        "max_input_tokens",
                        "input_token_limit",
                    ):
                        val = m.get(field)
                        if val and isinstance(val, (int, float)) and val > 0:
                            api_ctx = int(val)
                            break

                    if not api_ctx:
                        metadata_blocks = (
                            m.get("meta"),
                            m.get("model_extra"),
                            m.get("capabilities"),
                            m.get("limits"),
                        )
                        for meta in metadata_blocks:
                            if not isinstance(meta, dict):
                                continue
                            # n_ctx is the actual serving context (set via -c flag in llama.cpp)
                            for field in (
                                "n_ctx",
                                "context_length",
                                "context_window",
                                "max_model_len",
                                "max_context_length",
                                "max_input_tokens",
                                "input_token_limit",
                            ):
                                val = meta.get(field)
                                if val and isinstance(val, (int, float)) and val > 0:
                                    api_ctx = int(val)
                                    break
                            if api_ctx:
                                break
                    break
    except Exception as e:
        logger.debug(f"Failed to query context length for {model}: {e}")

    # For local/self-hosted endpoints, trust the API value (user set --max-model-len)
    # For cloud APIs, use the larger value (API can report low defaults)
    if api_ctx and known:
        _is_local = _is_local_endpoint(endpoint_url)
        if _is_local and api_ctx < known:
            logger.info(f"Local endpoint reports {api_ctx} for {model} (known max: {known}) — using API value")
            return api_ctx
        result = max(api_ctx, known)
        if api_ctx < known:
            logger.info(f"API reported {api_ctx} for {model}, using known {known} instead")
        return _apply_provider_context_limit(endpoint_url, model, result)
    if api_ctx:
        return _apply_provider_context_limit(endpoint_url, model, api_ctx)
    if known:
        logger.info(f"Using known context window for {model}: {known}")
        return _apply_provider_context_limit(endpoint_url, model, known)

    return DEFAULT_CONTEXT


def estimate_tokens(messages: List[Dict]) -> int:
    """Rough token estimate for a list of messages.

    Uses chars * 0.3 which is closer to real BPE tokenizer output
    than the commonly-cited chars/4 (which underestimates by ~20-30%).
    Also adds ~4 tokens per message for role/formatting overhead.
    """
    total = 0
    for msg in messages:
        total += 4  # per-message overhead (role, separators)
        content = msg.get("content", "")
        if isinstance(content, str):
            total += int(len(content) * 0.3)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    total += int(len(item.get("text", "")) * 0.3)
    return total
