import os
import secrets
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

from src.desktop_biometric import (
    BIOMETRIC_SECRET_ENV,
    BIOMETRIC_TOKEN_TTL,
    issue_biometric_token,
)

try:
    import webview
except Exception:
    webview = None


PROJECT_DIR = Path(__file__).resolve().parent
PORT = int(os.environ.get("ODYSSEUS_DESKTOP_PORT", "7001"))
HOST = "127.0.0.1"
URL = f"http://{HOST}:{PORT}"
APP_NAME = "Odysseus"
_ABOUT_PANEL_CONTROLLER = None
_LA_CONTEXT_CLASS = None
_TOUCH_ID_POLICY = 1
_TOUCH_ID_BIOMETRY_TYPE = 1


def _app_version() -> str:
    version = os.environ.get("ODYSSEUS_APP_VERSION", "").strip()
    if version:
        return version

    version_file = PROJECT_DIR / "VERSION"
    try:
        version = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        version = ""
    return version or "1.0"


def _configure_macos_app_metadata() -> Path | None:
    if sys.platform != "darwin":
        return None

    try:
        import AppKit

        version = _app_version()
        bundle = AppKit.NSBundle.mainBundle()
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        info["CFBundleName"] = APP_NAME
        info["CFBundleDisplayName"] = APP_NAME
        info["CFBundleShortVersionString"] = version
        info["CFBundleVersion"] = version
        info["CFBundleGetInfoString"] = f"{APP_NAME} {version}"

        icon_path = next(
            (
                path
                for path in (
                    PROJECT_DIR / "assets" / "Odysseus.icns",
                    PROJECT_DIR / "static" / "icon-512.png",
                )
                if path.is_file()
            ),
            None,
        )
        if icon_path is not None:
            icon = AppKit.NSImage.alloc().initByReferencingFile_(str(icon_path))
            if icon is not None:
                AppKit.NSApplication.sharedApplication().setApplicationIconImage_(icon)
        return icon_path
    except Exception as exc:
        print(f"Unable to configure macOS app metadata: {exc}", file=sys.stderr)
        return None


def _install_macos_about_panel(window) -> None:
    if sys.platform != "darwin" or window is None:
        return
    if not window.events.shown.wait(10):
        return

    try:
        import AppKit
        from PyObjCTools import AppHelper

        version = _app_version()
        icon_path = next(
            (
                path
                for path in (
                    PROJECT_DIR / "assets" / "Odysseus.icns",
                    PROJECT_DIR / "static" / "icon-512.png",
                )
                if path.is_file()
            ),
            None,
        )

        def install() -> None:
            global _ABOUT_PANEL_CONTROLLER
            if _ABOUT_PANEL_CONTROLLER is not None:
                return

            options = {
                AppKit.NSAboutPanelOptionApplicationName: APP_NAME,
                AppKit.NSAboutPanelOptionApplicationVersion: version,
                AppKit.NSAboutPanelOptionVersion: "",
            }
            if icon_path is not None:
                icon = AppKit.NSImage.alloc().initByReferencingFile_(str(icon_path))
                if icon is not None:
                    options[AppKit.NSAboutPanelOptionApplicationIcon] = icon

            class AboutPanelController(AppKit.NSObject):
                about_options = None

                def showAbout_(self, _sender):
                    AppKit.NSApplication.sharedApplication().orderFrontStandardAboutPanelWithOptions_(
                        self.about_options
                    )

            controller = AboutPanelController.alloc().init()
            controller.about_options = options

            main_menu = AppKit.NSApplication.sharedApplication().mainMenu()
            app_menu_item = main_menu.itemAtIndex_(0) if main_menu is not None else None
            app_menu = app_menu_item.submenu() if app_menu_item is not None else None
            about_item = app_menu.itemAtIndex_(0) if app_menu is not None else None
            if about_item is None:
                return

            about_item.setTarget_(controller)
            about_item.setAction_("showAbout:")
            _ABOUT_PANEL_CONTROLLER = controller

        AppHelper.callAfter(install)
    except Exception as exc:
        print(f"Unable to install macOS About panel: {exc}", file=sys.stderr)


def _local_auth_context_class():
    global _LA_CONTEXT_CLASS
    if _LA_CONTEXT_CLASS is not None:
        return _LA_CONTEXT_CLASS
    if sys.platform != "darwin":
        raise RuntimeError("Touch ID is only available on macOS")

    import objc

    objc.loadBundle(
        "LocalAuthentication",
        globals(),
        bundle_path="/System/Library/Frameworks/LocalAuthentication.framework",
    )
    _LA_CONTEXT_CLASS = objc.lookUpClass("LAContext")
    return _LA_CONTEXT_CLASS


class DesktopApi:
    """Native-only APIs exposed to the trusted pywebview page."""

    def touch_id_status(self) -> dict:
        try:
            context = _local_auth_context_class().alloc().init()
            available = bool(
                context.canEvaluatePolicy_error_(_TOUCH_ID_POLICY, None)
            )
            is_touch_id = int(context.biometryType()) == _TOUCH_ID_BIOMETRY_TYPE
            return {
                "available": available and is_touch_id,
                "biometry": "touch_id" if is_touch_id else "unavailable",
            }
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def authorize_touch_id(self, username: str) -> dict:
        status = self.touch_id_status()
        if not status.get("available"):
            return {"ok": False, "error": "Touch ID is not available on this Mac"}

        context = _local_auth_context_class().alloc().init()
        if hasattr(context, "setLocalizedFallbackTitle_"):
            context.setLocalizedFallbackTitle_("")

        completed = threading.Event()
        result = {"ok": False, "error": "Touch ID verification failed"}

        def reply(success, error):
            if success:
                result["ok"] = True
                result.pop("error", None)
            elif error is not None:
                try:
                    result["error"] = str(error.localizedDescription())
                except Exception:
                    pass
            completed.set()

        context.evaluatePolicy_localizedReason_reply_(
            _TOUCH_ID_POLICY,
            "Authorize changing your Odysseus password.",
            reply,
        )
        if not completed.wait(60):
            context.invalidate()
            return {"ok": False, "error": "Touch ID verification timed out"}
        if not result.get("ok"):
            return result

        try:
            result["token"] = issue_biometric_token(username)
            result["expires_at"] = int(time.time()) + BIOMETRIC_TOKEN_TTL
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


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
    os.environ.setdefault(BIOMETRIC_SECRET_ENV, secrets.token_urlsafe(48))
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

    icon_path = _configure_macos_app_metadata()
    window = webview.create_window(
        title=APP_NAME,
        url=URL,
        js_api=DesktopApi(),
        width=1440,
        height=940,
        min_size=(1040, 720),
        background_color="#0c0b0a",
        text_select=True,
    )
    webview.start(
        func=_install_macos_about_panel,
        args=(window,),
        icon=str(icon_path) if icon_path is not None else None,
    )


if __name__ == "__main__":
    main()
