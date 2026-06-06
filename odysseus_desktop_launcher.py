import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from shutil import which

import uvicorn

try:
    import webview
except Exception:
    webview = None


PROJECT_DIR = Path(__file__).resolve().parent
PORT = int(os.environ.get("ODYSSEUS_DESKTOP_PORT", "7001"))
HOST = "127.0.0.1"
URL = f"http://{HOST}:{PORT}"


def _prepend_path(*paths: Path | str) -> None:
    current = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    for raw in reversed(paths):
        path = str(raw)
        if path and Path(path).exists() and path not in current:
            current.insert(0, path)
    os.environ["PATH"] = os.pathsep.join(current)


def _is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.35)
        return sock.connect_ex((host, port)) == 0


def _wait_for_server(timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{URL}/api/health", timeout=0.8) as response:
                if response.status < 500:
                    return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def _wait_for_port(host: str, port: int, timeout: float = 8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_port_open(host, port):
            return True
        time.sleep(0.25)
    return False


def _start_background(command: list[str], log_name: str, env: dict[str, str] | None = None) -> None:
    PROJECT_DIR.joinpath("logs").mkdir(exist_ok=True)
    log_file = PROJECT_DIR / "logs" / log_name
    stdout = log_file.open("ab")
    try:
        subprocess.Popen(
            command,
            cwd=str(PROJECT_DIR),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=subprocess.STDOUT,
            env=env or os.environ.copy(),
            start_new_session=True,
        )
    except Exception:
        stdout.close()


def _try_start_lm_studio() -> None:
    lms = Path.home() / ".lmstudio" / "bin" / "lms"
    if not lms.exists():
        return
    try:
        subprocess.Popen(
            [str(lms), "server", "start", "--port", "1234"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _try_start_chroma() -> None:
    host = os.environ.get("CHROMADB_HOST", "127.0.0.1")
    port = int(os.environ.get("CHROMADB_PORT", "8100"))
    check_host = "127.0.0.1" if host in {"localhost", "0.0.0.0"} else host
    if _is_port_open(check_host, port):
        return

    chroma = which("chroma") or str(PROJECT_DIR / ".venv311" / "bin" / "chroma")
    if not Path(chroma).exists():
        return
    data_dir = PROJECT_DIR / "data" / "chroma"
    data_dir.mkdir(parents=True, exist_ok=True)
    _start_background(
        [
            chroma,
            "run",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--path",
            str(data_dir),
        ],
        "chroma.log",
    )
    _wait_for_port("127.0.0.1", port, timeout=10.0)


def _try_start_hermes() -> None:
    if os.environ.get("ODYSSEUS_START_HERMES", "1").strip().lower() in {"0", "false", "no", "off"}:
        return
    host = os.environ.get("API_SERVER_HOST", "127.0.0.1")
    port = int(os.environ.get("API_SERVER_PORT", "8642"))
    check_host = "127.0.0.1" if host in {"localhost", "0.0.0.0"} else host
    if _is_port_open(check_host, port):
        return

    candidates = [
        PROJECT_DIR / ".hermes-venv" / "bin" / "hermes",
        Path.home() / ".local" / "bin" / "hermes",
    ]
    hermes = which("hermes")
    if not hermes:
        hermes = next((str(path) for path in candidates if path.exists()), "")
    if not hermes:
        return

    env = os.environ.copy()
    env.setdefault("HERMES_HOME", str(Path.home() / ".hermes"))
    env.setdefault("API_SERVER_ENABLED", "true")
    env.setdefault("API_SERVER_HOST", "127.0.0.1")
    env.setdefault("API_SERVER_PORT", str(port))
    env.setdefault("API_SERVER_KEY", "change-me-local-dev")
    env.setdefault("API_SERVER_MODEL_NAME", "hermes-agent")
    env.setdefault("LM_BASE_URL", "http://localhost:1234/v1")
    env.setdefault("LM_API_KEY", "lmstudio")
    env.setdefault("HERMES_ACCEPT_HOOKS", "1")
    _start_background([hermes, "gateway", "--accept-hooks", "run"], "hermes_gateway.log", env=env)
    _wait_for_port("127.0.0.1", port, timeout=15.0)


def _start_odysseus() -> None:
    os.chdir(PROJECT_DIR)
    _prepend_path(
        PROJECT_DIR / ".venv311" / "bin",
        PROJECT_DIR / ".hermes-venv" / "bin",
        Path.home() / ".local" / "node" / "bin",
        Path.home() / ".lmstudio" / "bin",
        "/opt/homebrew/bin",
        "/usr/local/bin",
    )
    os.environ.setdefault("AUTH_ENABLED", "true")
    os.environ.setdefault("LOCALHOST_BYPASS", "true")
    os.environ.setdefault("LLM_HOST", "localhost")
    os.environ.setdefault("LLM_HOSTS", "localhost:1234")
    os.environ.setdefault("SEARXNG_INSTANCE", "http://localhost:8080")
    os.environ.setdefault("ODYSSEUS_DESKTOP", "1")
    os.environ.setdefault("ODYSSEUS_INPROCESS_POLLERS", "0")
    os.environ.setdefault("CHROMADB_HOST", "127.0.0.1")
    os.environ.setdefault("CHROMADB_PORT", "8100")
    os.environ.setdefault("API_SERVER_ENABLED", "true")
    os.environ.setdefault("API_SERVER_HOST", "127.0.0.1")
    os.environ.setdefault("API_SERVER_PORT", "8642")
    os.environ.setdefault("API_SERVER_KEY", "change-me-local-dev")
    os.environ.setdefault("API_SERVER_MODEL_NAME", "hermes-agent")
    os.environ.setdefault("LM_BASE_URL", "http://localhost:1234/v1")
    os.environ.setdefault("LM_API_KEY", "lmstudio")

    _try_start_lm_studio()
    _try_start_chroma()
    _try_start_hermes()

    if _is_port_open(HOST, PORT):
        return

    from app import app

    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level="info",
        access_log=False,
    )


def main() -> None:
    PROJECT_DIR.joinpath("logs").mkdir(exist_ok=True)
    server_thread = threading.Thread(target=_start_odysseus, daemon=True)
    server_thread.start()

    _wait_for_server()
    if webview is None:
        webbrowser.open(URL)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return

    webview.create_window(
        title="Odysseus",
        url=URL,
        width=1440,
        height=940,
        min_size=(1040, 720),
        background_color="#0c0b0a",
    )
    webview.start()


if __name__ == "__main__":
    main()
