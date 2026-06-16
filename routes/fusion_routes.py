"""Fusion MCP team configuration routes."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from core.atomic_io import atomic_write_json
from core.middleware import require_admin
from src.settings import load_settings as _load_settings, save_settings as _save_settings


FUSION_ROOT = Path(
    os.environ.get(
        "FUSION_MCP_ROOT",
        str(Path.home() / ".local" / "share" / "antigravity-fusion-mcp"),
    )
).expanduser()
FUSION_CONFIG_DIR = FUSION_ROOT / "config"
REGISTRY_PATH = FUSION_CONFIG_DIR / "model_registry.json"
PANELS_PATH = FUSION_CONFIG_DIR / "panels.json"
PROVIDERS_PATH = FUSION_CONFIG_DIR / "providers.json"
SERVER_PATH = FUSION_ROOT / "server.mjs"

_ROLE_OPTIONS = [
    "leader",
    "worker",
    "critic",
    "reviewer",
    "judge",
    "design_lead",
    "ux_reviewer",
    "visual_designer",
    "frontend_designer",
    "planner",
    "researcher",
]
_MODE_OPTIONS = ["single", "council", "lead_worker"]


def _read_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError(f"{path.name} must be an object")
        return data
    except FileNotFoundError as exc:
        raise HTTPException(404, f"Fusion config missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"Fusion config invalid JSON: {path.name}") from exc


def _backup(path: Path) -> None:
    if not path.exists():
        return
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, path.with_name(f"{path.name}.{stamp}.bak"))


def _write_json(path: Path, data: dict) -> None:
    _backup(path)
    atomic_write_json(str(path), data, indent=2)


def _provider_accounts(providers: dict) -> list[dict[str, Any]]:
    clean = []
    for provider in providers.get("providers") or []:
        if not isinstance(provider, dict):
            continue
        clean.append(
            {
                "id": str(provider.get("id") or ""),
                "label": str(provider.get("label") or provider.get("id") or ""),
                "enabled": provider.get("enabled") is not False,
                "rpm": provider.get("rpm") or 60,
                "accounts": [
                    {
                        "id": str(account.get("id") or ""),
                        "label": str(account.get("label") or account.get("id") or ""),
                        "enabled": account.get("enabled") is not False,
                        "rpm": account.get("rpm") or provider.get("rpm") or 60,
                    }
                    for account in (provider.get("accounts") or [])
                    if isinstance(account, dict)
                ],
            }
        )
    return clean


def _model_summary(model: dict) -> dict:
    health = model.get("health") if isinstance(model.get("health"), dict) else {}
    status = health.get("status") or model.get("verified") or "unknown"
    return {
        "id": str(model.get("id") or ""),
        "provider": str(model.get("provider") or ""),
        "model": str(model.get("model") or ""),
        "label": str(model.get("label") or model.get("model") or model.get("id") or ""),
        "roles": model.get("roles") if isinstance(model.get("roles"), list) else [],
        "capabilities": model.get("capabilities") if isinstance(model.get("capabilities"), list) else [],
        "latency_tier": model.get("latency_tier") or "unknown",
        "health_status": status,
        "usable": bool(health.get("usable") or status in (True, "ok", "detected")),
        "account_id": health.get("account_id") or model.get("detected_by") or "",
        "score": model.get("score"),
    }


def _sanitize_member(member: dict, registry_ids: set[str], providers: dict) -> dict:
    role = str(member.get("role") or "worker").strip() or "worker"
    model_id = str(member.get("model_id") or "").strip()
    if model_id not in registry_ids:
        raise HTTPException(400, f"Unknown Fusion model: {model_id}")

    fallback_ids = []
    for value in member.get("fallback_model_ids") or []:
        item = str(value or "").strip()
        if item and item in registry_ids and item != model_id and item not in fallback_ids:
            fallback_ids.append(item)

    provider_ids = {str(p.get("id")) for p in providers.get("providers") or [] if isinstance(p, dict)}
    account_by_provider = {}
    raw_account_by_provider = member.get("account_by_provider")
    if isinstance(raw_account_by_provider, dict):
        for provider_id, account_id in raw_account_by_provider.items():
            provider_id = str(provider_id or "").strip()
            account_id = str(account_id or "").strip()
            if provider_id in provider_ids and account_id:
                account_by_provider[provider_id] = account_id

    clean = {
        "role": role,
        "model_id": model_id,
    }
    if fallback_ids:
        clean["fallback_model_ids"] = fallback_ids[:5]
    if account_by_provider:
        clean["account_by_provider"] = account_by_provider
    return clean


def _sanitize_panel(raw_panel: dict, registry: dict, providers: dict) -> dict:
    if not isinstance(raw_panel, dict):
        raise HTTPException(400, "panel must be an object")
    registry_ids = {str(model.get("id")) for model in registry.get("models") or [] if isinstance(model, dict)}
    panel_id = str(raw_panel.get("id") or "").strip()
    if not panel_id:
        raise HTTPException(400, "panel.id is required")
    label = str(raw_panel.get("label") or panel_id).strip() or panel_id
    mode = str(raw_panel.get("mode") or "lead_worker").strip()
    if mode not in _MODE_OPTIONS:
        raise HTTPException(400, "panel.mode must be single, council, or lead_worker")
    members = [
        _sanitize_member(member, registry_ids, providers)
        for member in (raw_panel.get("members") or [])
        if isinstance(member, dict)
    ]
    if not members:
        raise HTTPException(400, "panel needs at least one member")
    timeout_ms = int(raw_panel.get("timeout_ms") or 75_000)
    timeout_ms = max(5_000, min(timeout_ms, 300_000))
    account_strategy = str(raw_panel.get("account_strategy") or "spread").strip()
    if account_strategy not in {"spread", "none"}:
        account_strategy = "spread"

    clean = {
        "id": panel_id,
        "label": label,
        "description": str(raw_panel.get("description") or "").strip(),
        "mode": mode,
        "timeout_ms": timeout_ms,
        "account_strategy": account_strategy,
        "members": members,
    }

    judge_model_id = str(raw_panel.get("judge_model_id") or "").strip()
    if judge_model_id and judge_model_id in registry_ids:
        clean["judge_model_id"] = judge_model_id
    execution_style = str(raw_panel.get("execution_style") or "").strip()
    if execution_style:
        clean["execution_style"] = execution_style

    existing_benchmark = raw_panel.get("panel_benchmark")
    if isinstance(existing_benchmark, dict):
        clean["panel_benchmark"] = existing_benchmark
    existing_history = raw_panel.get("panel_benchmark_history")
    if isinstance(existing_history, list):
        clean["panel_benchmark_history"] = existing_history[:8]
    clean["edited_in_odysseus_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return clean


def _upsert_panel(panel: dict) -> dict:
    panels_config = _read_json(PANELS_PATH)
    panels = [p for p in (panels_config.get("panels") or []) if isinstance(p, dict)]
    index = next((i for i, item in enumerate(panels) if item.get("id") == panel["id"]), -1)
    if index >= 0:
        previous = panels[index]
        panel["panel_benchmark"] = previous.get("panel_benchmark", panel.get("panel_benchmark"))
        panel["panel_benchmark_history"] = previous.get("panel_benchmark_history", panel.get("panel_benchmark_history", []))
        panels[index] = panel
    else:
        panels.append(panel)
    panels_config = {**panels_config, "panels": panels}
    _write_json(PANELS_PATH, panels_config)
    return panel


def _panel_model_ids(panel: dict) -> list[str]:
    ids: list[str] = []
    for member in panel.get("members") or []:
        if not isinstance(member, dict):
            continue
        for value in [member.get("model_id"), *(member.get("fallback_model_ids") or [])]:
            model_id = str(value or "").strip()
            if model_id and model_id not in ids:
                ids.append(model_id)
    judge_model_id = str(panel.get("judge_model_id") or "").strip()
    if judge_model_id and judge_model_id not in ids:
        ids.append(judge_model_id)
    return ids


def _group_model_ids_by_provider(model_ids: list[str], registry: dict) -> dict[str, list[str]]:
    registry_by_id = {
        str(model.get("id") or ""): model
        for model in registry.get("models") or []
        if isinstance(model, dict)
    }
    grouped: dict[str, list[str]] = {}
    for model_id in model_ids:
        model = registry_by_id.get(model_id)
        provider_id = str((model or {}).get("provider") or "").strip()
        if not provider_id and ":" in model_id:
            provider_id = model_id.split(":", 1)[0]
        if not provider_id:
            continue
        grouped.setdefault(provider_id, []).append(model_id)
    return grouped


def _enabled_provider_ids(providers: dict) -> set[str]:
    return {
        str(provider.get("id") or "")
        for provider in providers.get("providers") or []
        if isinstance(provider, dict)
        and provider.get("enabled") is not False
        and str(provider.get("id") or "")
    }


def _registry_model_ids(registry: dict, provider_ids: set[str] | None = None) -> list[str]:
    ids: list[str] = []
    for model in registry.get("models") or []:
        if not isinstance(model, dict):
            continue
        provider_id = str(model.get("provider") or "").strip()
        model_id = str(model.get("id") or "").strip()
        if not model_id:
            continue
        if provider_ids is not None and provider_id not in provider_ids:
            continue
        if model_id not in ids:
            ids.append(model_id)
    return ids


def _chunks(values: list[str], size: int) -> list[list[str]]:
    size = max(1, size)
    return [values[i:i + size] for i in range(0, len(values), size)]


def _node_bin() -> str:
    bundled = Path.home() / ".local" / "node" / "bin" / "node"
    if bundled.exists():
        return str(bundled)
    found = shutil.which("node")
    if found:
        return found
    raise HTTPException(500, "Node.js not found; cannot score Fusion panels.")


def _run_mcp_tool(name: str, args: dict | None = None, timeout: int = 60) -> dict:
    if not SERVER_PATH.exists():
        raise HTTPException(404, f"Fusion MCP server missing: {SERVER_PATH}")
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "odysseus-fusion-routes", "version": "1.0.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": args or {}}},
    ]
    proc = subprocess.run(
        [_node_bin(), str(SERVER_PATH)],
        cwd=str(FUSION_ROOT),
        input="\n".join(json.dumps(item) for item in messages) + "\n",
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise HTTPException(500, proc.stderr.strip() or f"Fusion MCP exited with {proc.returncode}")
    for line in reversed([line for line in proc.stdout.splitlines() if line.strip()]):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("id") != 2:
            continue
        result = payload.get("result") or {}
        if result.get("isError"):
            text = ((result.get("content") or [{}])[0] or {}).get("text") or "Fusion MCP tool failed"
            raise HTTPException(500, text)
        text = ((result.get("content") or [{}])[0] or {}).get("text")
        if not text:
            return result
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}
    raise HTTPException(500, "No Fusion MCP response.")


def setup_fusion_routes():
    router = APIRouter(prefix="/api/fusion", tags=["fusion"])

    @router.get("/state")
    async def get_fusion_state(request: Request):
        require_admin(request)
        registry = _read_json(REGISTRY_PATH)
        panels = _read_json(PANELS_PATH)
        providers = _read_json(PROVIDERS_PATH)
        settings = _load_settings()
        return {
            "root": str(FUSION_ROOT),
            "settings": {
                "enabled": bool(settings.get("fusion_subagent_enabled")),
                "panel": settings.get("fusion_subagent_panel") or "",
                "depth": settings.get("fusion_subagent_depth") or "fast",
                "max_agents": settings.get("fusion_subagent_max_agents") or 3,
            },
            "providers": _provider_accounts(providers),
            "models": [_model_summary(model) for model in registry.get("models") or [] if isinstance(model, dict)],
            "panels": panels.get("panels") or [],
            "role_options": _ROLE_OPTIONS,
            "mode_options": _MODE_OPTIONS,
        }

    @router.post("/panel")
    async def save_fusion_panel(request: Request):
        require_admin(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "request body must be an object")
        registry = _read_json(REGISTRY_PATH)
        providers = _read_json(PROVIDERS_PATH)
        raw_panel = body.get("panel")
        panel = _sanitize_panel(raw_panel, registry, providers)
        _upsert_panel(panel)
        score = _run_mcp_tool("fusion_score_panels", {"panel_ids": [panel["id"]], "write_panels": True})

        if body.get("make_default"):
            settings = _load_settings()
            settings["fusion_subagent_panel"] = panel["id"]
            _save_settings(settings)

        refreshed = _read_json(PANELS_PATH)
        saved = next((item for item in refreshed.get("panels") or [] if item.get("id") == panel["id"]), panel)
        return {"ok": True, "panel": saved, "score": score}

    @router.post("/default-panel")
    async def set_default_fusion_panel(request: Request):
        require_admin(request)
        body = await request.json()
        panel_id = str((body or {}).get("panel_id") or "").strip()
        if panel_id:
            panels = _read_json(PANELS_PATH)
            if not any(item.get("id") == panel_id for item in panels.get("panels") or [] if isinstance(item, dict)):
                raise HTTPException(400, f"Unknown Fusion panel: {panel_id}")
        settings = _load_settings()
        settings["fusion_subagent_panel"] = panel_id
        _save_settings(settings)
        return {"ok": True, "panel_id": panel_id}

    @router.post("/score")
    async def score_fusion_panel(request: Request):
        require_admin(request)
        body = await request.json()
        panel_ids = body.get("panel_ids") if isinstance(body, dict) else None
        if panel_ids is not None and not isinstance(panel_ids, list):
            raise HTTPException(400, "panel_ids must be a list")
        result = _run_mcp_tool("fusion_score_panels", {"panel_ids": panel_ids or None, "write_panels": True})
        return {"ok": True, "score": result, "panels": _read_json(PANELS_PATH).get("panels") or []}

    @router.post("/test-panel")
    async def test_fusion_panel(request: Request):
        require_admin(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "request body must be an object")
        registry = _read_json(REGISTRY_PATH)
        providers = _read_json(PROVIDERS_PATH)
        panel = _sanitize_panel(body.get("panel"), registry, providers)
        _upsert_panel(panel)
        grouped = _group_model_ids_by_provider(_panel_model_ids(panel), registry)
        audits = []
        for provider_id, model_ids in grouped.items():
            audits.append(
                {
                    "provider": provider_id,
                    "result": _run_mcp_tool(
                        "fusion_audit_models",
                        {
                            "provider": provider_id,
                            "model_ids": model_ids[:80],
                            "limit": len(model_ids[:80]),
                            "only_unchecked": False,
                            "stale_hours": 0.01,
                            "write_registry": True,
                            "timeout_ms": int(body.get("timeout_ms") or 15000),
                            "concurrency": int(body.get("concurrency") or 2),
                            "max_accounts": int(body.get("max_accounts") or 2),
                        },
                        timeout=max(30, min(180, len(model_ids) * 25)),
                    ),
                }
            )
        score = _run_mcp_tool("fusion_score_panels", {"panel_ids": [panel["id"]], "write_panels": True})
        refreshed = _read_json(PANELS_PATH)
        registry_after = _read_json(REGISTRY_PATH)
        saved = next((item for item in refreshed.get("panels") or [] if item.get("id") == panel["id"]), panel)
        return {
            "ok": True,
            "panel": saved,
            "audits": audits,
            "score": score,
            "models": [_model_summary(model) for model in registry_after.get("models") or [] if isinstance(model, dict)],
            "panels": refreshed.get("panels") or [],
        }

    @router.post("/audit-models")
    async def audit_fusion_models(request: Request):
        require_admin(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "request body must be an object")

        registry = _read_json(REGISTRY_PATH)
        providers = _read_json(PROVIDERS_PATH)
        provider = str(body.get("provider") or "enabled").strip()
        scope = str(body.get("scope") or "enabled").strip()
        model_ids = [str(item or "").strip() for item in body.get("model_ids") or [] if str(item or "").strip()]
        explicit_model_ids = bool(model_ids)

        if not model_ids and isinstance(body.get("panel"), dict):
            panel = _sanitize_panel(body.get("panel"), registry, providers)
            model_ids = _panel_model_ids(panel)
            explicit_model_ids = True

        if not model_ids:
            if provider and provider not in {"all", "enabled"}:
                provider_ids = {provider}
            elif scope == "all":
                provider_ids = None
            else:
                provider_ids = _enabled_provider_ids(providers)
            model_ids = _registry_model_ids(registry, provider_ids)

        max_models = int(body.get("max_models") or 160)
        max_models = max(1, min(max_models, 400))
        model_ids = model_ids[:max_models]
        grouped = _group_model_ids_by_provider(model_ids, registry)

        chunk_size = int(body.get("batch_limit") or 80)
        chunk_size = max(1, min(chunk_size, 80))
        timeout_ms = int(body.get("timeout_ms") or 12_000)
        timeout_ms = max(3_000, min(timeout_ms, 60_000))
        concurrency = int(body.get("concurrency") or 2)
        concurrency = max(1, min(concurrency, 4))
        max_accounts = int(body.get("max_accounts") or 1)
        max_accounts = max(1, min(max_accounts, 4))
        stale_hours = float(body.get("stale_hours") or 12)
        stale_hours = max(0.01, min(stale_hours, 720))
        only_unchecked = body.get("only_unchecked")
        only_unchecked = True if only_unchecked is None else bool(only_unchecked)

        audits = []
        summary = {"audited": 0, "ok": 0, "dead": 0, "temporary_failed": 0, "auth": 0, "failed": 0}
        for provider_id, ids in grouped.items():
            batches = _chunks(ids, chunk_size) if explicit_model_ids else [[]]
            for chunk in batches:
                args = {
                    "provider": provider_id,
                    "limit": len(chunk) if explicit_model_ids else chunk_size,
                    "only_unchecked": only_unchecked,
                    "stale_hours": stale_hours,
                    "write_registry": True,
                    "timeout_ms": timeout_ms,
                    "concurrency": concurrency,
                    "max_accounts": max_accounts,
                }
                if explicit_model_ids:
                    args["model_ids"] = chunk
                result = _run_mcp_tool(
                    "fusion_audit_models",
                    args,
                    timeout=max(30, min(240, max(len(chunk), 1) * 20)),
                )
                item = (result.get("summary") if isinstance(result, dict) else {}) or {}
                for key in summary:
                    summary[key] += int(item.get(key) or 0)
                audits.append({"provider": provider_id, "count": len(chunk), "result": result})

        registry_after = _read_json(REGISTRY_PATH)
        panels_after = _read_json(PANELS_PATH)
        return {
            "ok": True,
            "summary": summary,
            "audits": audits,
            "models": [_model_summary(model) for model in registry_after.get("models") or [] if isinstance(model, dict)],
            "panels": panels_after.get("panels") or [],
        }

    return router
