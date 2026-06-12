"""Normalize per-request reasoning preferences across model providers."""

from __future__ import annotations

from typing import Dict, List, Optional


_ALIASES = {
    "": "auto",
    "auto": "auto",
    "default": "auto",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "extra-high": "xhigh",
    "extra_high": "xhigh",
    "extra high": "xhigh",
    "extreme": "xhigh",
    "max": "xhigh",
    "xhigh": "xhigh",
}

_GUIDANCE = {
    "low": (
        "Reasoning preference: low. Think internally only as much as needed, "
        "then give a concise answer without exposing private chain-of-thought."
    ),
    "medium": (
        "Reasoning preference: medium. Check the important steps internally "
        "before answering, but do not expose private chain-of-thought."
    ),
    "high": (
        "Reasoning preference: high. Analyze carefully, verify assumptions and "
        "edge cases internally, then give the answer without private chain-of-thought."
    ),
    "xhigh": (
        "Reasoning preference: extra high. Use the deepest practical internal "
        "analysis, cross-check the result and important edge cases, then give the "
        "answer without exposing private chain-of-thought."
    ),
}

_API_REASONING_PREFIXES = (
    "o1",
    "o3",
    "o4",
    "gpt-5",
    "gpt-oss",
)


def normalize_reasoning_effort(value: object) -> str:
    """Return auto/low/medium/high/xhigh, defaulting invalid values to auto."""
    return _ALIASES.get(str(value or "").strip().lower(), "auto")


def apply_reasoning_guidance(messages: List[Dict], effort: object) -> List[Dict]:
    """Apply portable reasoning guidance without mutating caller-owned messages."""
    normalized = normalize_reasoning_effort(effort)
    copied = [dict(message) for message in (messages or [])]
    guidance = _GUIDANCE.get(normalized)
    if not guidance:
        return copied
    if copied and copied[0].get("role") == "system":
        copied[0]["content"] = f"{copied[0].get('content') or ''}\n\n{guidance}".strip()
    else:
        copied.insert(0, {"role": "system", "content": guidance})
    return copied


def api_reasoning_effort(model: str, effort: object) -> Optional[str]:
    """Map the preference to OpenAI-compatible reasoning_effort when supported."""
    normalized = normalize_reasoning_effort(effort)
    if normalized == "auto":
        return None
    basename = str(model or "").lower().rstrip("/").split("/")[-1]
    if not basename.startswith(_API_REASONING_PREFIXES):
        return None
    return "high" if normalized == "xhigh" else normalized
