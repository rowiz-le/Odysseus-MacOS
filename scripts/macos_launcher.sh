#!/usr/bin/env bash
set -euo pipefail

APP_NAME="Odysseus"
BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_INFO_PLIST="$BUNDLE_DIR/Info.plist"
PAYLOAD_DIR="$BUNDLE_DIR/Resources/app"
SUPPORT_ROOT="$HOME/Library/Application Support/$APP_NAME"
RUN_DIR="$SUPPORT_ROOT/app"
VENV_DIR="$SUPPORT_ROOT/.venv"
LOG_DIR="$SUPPORT_ROOT/logs"
BOOTSTRAP_LOG="$LOG_DIR/bootstrap.log"

mkdir -p "$SUPPORT_ROOT" "$LOG_DIR"
exec >>"$BOOTSTRAP_LOG" 2>&1

show_bootstrap_error() {
  local message="$1"
  /usr/bin/osascript - "$message" <<'APPLESCRIPT' >/dev/null 2>&1 || true
on run argv
  display dialog (item 1 of argv) buttons {"OK"} default button "OK" with icon stop
end run
APPLESCRIPT
}

on_bootstrap_error() {
  local exit_code="$?"
  local line_number="$1"
  echo "bootstrap failed at line $line_number with exit code $exit_code"
  show_bootstrap_error "Odysseus could not finish first-launch setup. Open ~/Library/Application Support/Odysseus/logs/bootstrap.log for details, then reopen the app."
  exit "$exit_code"
}
trap 'on_bootstrap_error "$LINENO"' ERR

echo "============================================================"
echo "$(date) launching $APP_NAME"
echo "bundle: $BUNDLE_DIR"
echo "payload: $PAYLOAD_DIR"
echo "run dir: $RUN_DIR"

if [[ ! -d "$PAYLOAD_DIR" ]]; then
  osascript -e 'display dialog "Odysseus.app is missing its bundled app payload. Please reinstall Odysseus." buttons {"OK"} default button "OK" with icon stop' >/dev/null 2>&1 || true
  exit 1
fi

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

find_python() {
  local candidates=(
    "python3.11"
    "/opt/homebrew/bin/python3.11"
    "/usr/local/bin/python3.11"
    "$HOME/.local/bin/python3.11"
    "python3"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if command_exists "$candidate" || [[ -x "$candidate" ]]; then
      if "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
      then
        printf '%s\n' "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python || true)"
if [[ -z "${PYTHON_BIN:-}" ]]; then
  osascript <<'APPLESCRIPT' >/dev/null 2>&1 || true
display dialog "Odysseus needs Python 3.11 or newer on the first launch. Install Python 3.11, then open Odysseus again." buttons {"Open Python Download", "OK"} default button "Open Python Download" with icon caution
if button returned of result is "Open Python Download" then
  open location "https://www.python.org/downloads/macos/"
end if
APPLESCRIPT
  exit 1
fi

echo "python: $PYTHON_BIN"

if [[ ! -d "$RUN_DIR" ]]; then
  mkdir -p "$RUN_DIR"
fi

echo "syncing app payload"
rsync -a --delete \
  --include 'static/js/editor/build/***' \
  --exclude '.git/' \
  --exclude '.DS_Store' \
  --exclude '.env' \
  --exclude 'data/' \
  --exclude 'logs/' \
  --exclude '.venv/' \
  --exclude '.venv311/' \
  --exclude '.hermes-venv/' \
  --exclude 'venv/' \
  --exclude 'node_modules/' \
  --exclude 'dist/' \
  --exclude 'build/' \
  --exclude 'src/cache/' \
  --exclude 'docs/FIX_REPORT_*.md' \
  "$PAYLOAD_DIR"/ "$RUN_DIR"/

cd "$RUN_DIR"
mkdir -p data logs data/generated_images data/uploads data/personal_docs data/chroma

support_data_is_empty() {
  if [[ -f "data/auth.json" ]]; then
    return 1
  fi
  if [[ -f "data/app.db" ]]; then
    local session_count
    session_count="$("$PYTHON_BIN" - "$RUN_DIR/data/app.db" <<'PY' 2>/dev/null || true
import sqlite3, sys
try:
    con = sqlite3.connect(sys.argv[1])
    print(con.execute("select count(*) from sessions").fetchone()[0])
except Exception:
    print("")
PY
)"
    if [[ -n "$session_count" && "$session_count" != "0" ]]; then
      return 1
    fi
  fi
  return 0
}

migrate_data_if_empty() {
  if ! support_data_is_empty; then
    return
  fi

  local candidates=()
  # When testing a locally built app from <repo>/dist/Odysseus.app, recover
  # the developer data folder instead of presenting an empty first-run app.
  candidates+=("$(cd "$BUNDLE_DIR/../../.." >/dev/null 2>&1 && pwd)/data")
  candidates+=("$HOME/Documents/antigravity/epic-bell/data")

  local src
  for src in "${candidates[@]}"; do
    if [[ -f "$src/auth.json" && -f "$src/app.db" ]]; then
      echo "migrating existing Odysseus data from: $src"
      rsync -a "$src"/ "$RUN_DIR/data"/
      return
    fi
  done
}

migrate_data_if_empty

venv_is_usable() {
  [[ -d "$VENV_DIR" ]] || return 1
  [[ -x "$VENV_DIR/bin/python" ]] || return 1
  [[ -r "$VENV_DIR/pyvenv.cfg" && -w "$VENV_DIR/pyvenv.cfg" ]] || return 1
  [[ -w "$VENV_DIR" ]] || return 1
  "$VENV_DIR/bin/python" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
}

rebuild_venv() {
  local temp_venv="${VENV_DIR}.tmp.$$"
  local backup_venv=""

  rm -rf "$temp_venv"
  if [[ -e "$VENV_DIR" ]]; then
    backup_venv="${VENV_DIR}.broken.$(date +%s)"
    echo "moving unusable virtual environment to: $backup_venv"
    if ! mv "$VENV_DIR" "$backup_venv"; then
      chmod -R u+rwX "$VENV_DIR" 2>/dev/null || true
      mv "$VENV_DIR" "$backup_venv"
    fi
  fi

  echo "creating virtual environment atomically"
  "$PYTHON_BIN" -m venv "$temp_venv"
  "$temp_venv/bin/python" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
  mv "$temp_venv" "$VENV_DIR"

  if [[ -n "$backup_venv" ]]; then
    rm -rf "$backup_venv"
  fi
}

if ! venv_is_usable; then
  rebuild_venv
fi

"$VENV_DIR/bin/python" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY

REQ_HASH="$(/usr/bin/shasum -a 256 "$RUN_DIR/requirements.txt" | awk '{print $1}')"
STAMP="$VENV_DIR/.odysseus-requirements.sha256"
if [[ ! -f "$STAMP" ]] || [[ "$(cat "$STAMP")" != "$REQ_HASH" ]]; then
  echo "installing/updating Python dependencies"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip
  "$VENV_DIR/bin/python" -m pip install -r "$RUN_DIR/requirements.txt"
  printf '%s' "$REQ_HASH" > "$STAMP"
fi

if [[ "${ODYSSEUS_BOOTSTRAP_ONLY:-0}" == "1" ]]; then
  echo "bootstrap-only validation completed"
  exit 0
fi

export AUTH_ENABLED="${AUTH_ENABLED:-true}"
export LOCALHOST_BYPASS="${LOCALHOST_BYPASS:-true}"
export ODYSSEUS_DESKTOP="${ODYSSEUS_DESKTOP:-1}"
export ODYSSEUS_DESKTOP_PORT="${ODYSSEUS_DESKTOP_PORT:-7001}"
export ODYSSEUS_INPROCESS_POLLERS="${ODYSSEUS_INPROCESS_POLLERS:-0}"
if [[ -z "${ODYSSEUS_APP_VERSION:-}" && -f "$APP_INFO_PLIST" ]]; then
  ODYSSEUS_APP_VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP_INFO_PLIST" 2>/dev/null || true)"
fi
export ODYSSEUS_APP_VERSION="${ODYSSEUS_APP_VERSION:-1.0}"
export LLM_HOST="${LLM_HOST:-localhost}"
export LLM_HOSTS="${LLM_HOSTS:-localhost:1234}"
export CHROMADB_HOST="${CHROMADB_HOST:-127.0.0.1}"
export CHROMADB_PORT="${CHROMADB_PORT:-8100}"
export PATH="$VENV_DIR/bin:$HOME/.lmstudio/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

echo "starting Odysseus"
exec "$VENV_DIR/bin/python" "$RUN_DIR/odysseus_desktop_launcher.py" >>"$LOG_DIR/odysseus_desktop.log" 2>&1
