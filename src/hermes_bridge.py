"""Bridge Odysseus Agent mode to a local Hermes Agent API server."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, Iterable, List, Optional

import httpx

from src.settings import get_setting

logger = logging.getLogger(__name__)


class HermesBridgeError(RuntimeError):
    """User-facing Hermes bridge failure."""


def _sse(data: Dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _done() -> str:
    return "data: [DONE]\n\n"


def _base_url() -> str:
    return str(get_setting("hermes_api_base", "http://127.0.0.1:8642/v1") or "").rstrip("/")


def _headers() -> Dict[str, str]:
    key = str(get_setting("hermes_api_key", "") or "").strip()
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def hermes_enabled() -> bool:
    return bool(get_setting("hermes_enabled", True))


def hermes_model() -> str:
    return str(get_setting("hermes_model", "hermes-agent") or "hermes-agent")


async def check_hermes_health(timeout: float = 2.0) -> None:
    if not hermes_enabled():
        raise HermesBridgeError("Hermes runtime is disabled in Settings.")
    base = _base_url()
    if not base:
        raise HermesBridgeError("Hermes API base URL is not configured.")

    candidates = []
    if base.endswith("/v1"):
        candidates.append(base[:-3] + "/health")
    candidates.append(base + "/health")

    async with httpx.AsyncClient(timeout=timeout) as client:
        last_error = None
        for url in candidates:
            try:
                r = await client.get(url, headers=_headers())
                if r.status_code < 400:
                    return
                last_error = f"{url} returned HTTP {r.status_code}"
            except Exception as e:
                last_error = str(e)
        raise HermesBridgeError(
            "Hermes chưa chạy hoặc chưa cấu hình. Start Hermes API Server ở "
            f"{base} trước khi chọn Hermes runtime. ({last_error})"
        )


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(p for p in parts if p).strip()
    return str(content or "")


def _latest_user_content(messages: List[Dict[str, Any]], fallback: str) -> Any:
    for msg in reversed(messages or []):
        if msg.get("role") == "user":
            return msg.get("content") or fallback
    return fallback


def _conversation_history(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    history = []
    for msg in messages or []:
        role = msg.get("role")
        if role not in {"system", "user", "assistant"}:
            continue
        content = msg.get("content", "")
        history.append({"role": role, "content": content})
    return history


def _extract_sse_payload(line: str) -> Optional[Any]:
    line = line.strip()
    if not line or line.startswith(":"):
        return None
    if line.startswith("data:"):
        line = line[5:].strip()
    if not line or line == "[DONE]":
        return line
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {"text": line}


def _event_delta(event: Dict[str, Any]) -> str:
    for key in ("delta", "text", "output_text", "content"):
        val = event.get(key)
        if isinstance(val, str):
            return val
    if isinstance(event.get("choices"), list) and event["choices"]:
        choice = event["choices"][0]
        delta = choice.get("delta") or choice.get("message") or {}
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str):
                return content
    if event.get("type") in {"response.output_text.delta", "chat.completion.chunk"}:
        val = event.get("delta")
        return val if isinstance(val, str) else ""
    return ""


def _map_hermes_event(event: Any, run_id: str) -> Iterable[str]:
    if event is None:
        return []
    if event == "[DONE]":
        return [_done()]
    if not isinstance(event, dict):
        return []

    etype = str(event.get("type") or event.get("object") or "")
    delta = _event_delta(event)
    if delta:
        return [_sse({"delta": delta})]

    if (
        "tool" in etype
        or etype.startswith("hermes.tool")
        or event.get("tool") is not None
        or event.get("tool_name") is not None
    ):
        tool = event.get("tool") or event.get("name") or event.get("tool_name") or "hermes_tool"
        status = event.get("status") or event.get("phase") or ""
        command = event.get("command") or event.get("input") or event.get("arguments") or status
        if isinstance(command, (dict, list)):
            command = json.dumps(command, ensure_ascii=False)
        if status in {"end", "done", "completed", "success"} or event.get("output") is not None:
            return [_sse({
                "type": "tool_output",
                "tool": tool,
                "command": str(command or "")[:500],
                "output": str(event.get("output") or event.get("result") or ""),
                "exit_code": 0 if not event.get("error") else 1,
            })]
        return [_sse({"type": "tool_start", "tool": tool, "command": str(command or "")[:500]})]

    if etype in {"response.completed", "run.completed"} or event.get("status") == "completed":
        output = event.get("output")
        if isinstance(output, str) and output:
            return [_sse({"delta": output}), _done()]
        return [_done()]

    if etype in {"response.failed", "run.failed"} or event.get("status") == "failed":
        msg = event.get("error") or event.get("message") or "Hermes run failed."
        return [f"event: error\ndata: {json.dumps({'message': str(msg), 'run_id': run_id}, ensure_ascii=False)}\n\n", _done()]

    if event.get("status") in {"started", "running"}:
        return [_sse({"type": "agent_step", "round": 1, "message": f"Hermes {event.get('status')}"})]

    return []


async def stop_hermes_run(run_id: str) -> None:
    if not run_id:
        return
    base = _base_url()
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            await client.post(f"{base}/runs/{run_id}/stop", headers=_headers())
        except Exception as e:
            logger.debug("Hermes stop failed for %s: %s", run_id, e)


async def stream_hermes_agent(
    *,
    messages: List[Dict[str, Any]],
    session_id: str,
    user_message: str,
    system_message: str = "",
    model: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Stream a Hermes Agent run as Odysseus-compatible SSE chunks."""
    await check_hermes_health()

    base = _base_url()
    model_name = model or hermes_model()
    latest_content = _latest_user_content(messages, user_message)
    history = _conversation_history(messages)
    payload = {
        "model": model_name,
        "input": latest_content if latest_content else user_message,
        "session_id": session_id,
        "conversation_history": history,
    }
    if system_message:
        payload["instructions"] = system_message

    run_id = ""
    started = time.time()
    completed = False

    timeout = httpx.Timeout(connect=5.0, read=None, write=30.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            create = await client.post(
                f"{base}/runs",
                headers={**_headers(), "Content-Type": "application/json"},
                json=payload,
            )
            if create.status_code >= 400:
                raise HermesBridgeError(
                    f"Hermes API rejected the run (HTTP {create.status_code}): {create.text[:500]}"
                )
            data = create.json() if create.content else {}
            run_id = str(data.get("run_id") or data.get("id") or "")
            if not run_id:
                raise HermesBridgeError(f"Hermes API did not return run_id: {data}")

            yield _sse({"type": "model_info", "model": model_name, "suffix": "Hermes"})
            yield _sse({"type": "agent_step", "round": 1, "message": "Hermes run started"})

            async with client.stream("GET", f"{base}/runs/{run_id}/events", headers=_headers()) as events:
                if events.status_code >= 400:
                    raise HermesBridgeError(
                        f"Hermes event stream failed (HTTP {events.status_code}): "
                        f"{(await events.aread()).decode('utf-8', errors='replace')[:500]}"
                    )
                async for line in events.aiter_lines():
                    payload = _extract_sse_payload(line)
                    for chunk in _map_hermes_event(payload, run_id):
                        if chunk == _done():
                            completed = True
                        yield chunk
                    await asyncio.sleep(0)

            if not completed:
                yield _sse({
                    "type": "metrics",
                    "data": {
                        "response_time": round(time.time() - started, 2),
                        "model": model_name,
                        "usage_source": "hermes",
                    },
                })
                yield _done()
                completed = True
        except asyncio.CancelledError:
            if run_id:
                await stop_hermes_run(run_id)
            raise
        except HermesBridgeError:
            raise
        except Exception as e:
            raise HermesBridgeError(f"Hermes bridge error: {e}") from e
        finally:
            if run_id and not completed:
                await stop_hermes_run(run_id)
