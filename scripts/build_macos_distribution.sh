#!/usr/bin/env bash
set -euo pipefail

APP_NAME="Odysseus"
BUNDLE_ID="com.odysseus.desktop"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
MACOS_DIR="$APP_BUNDLE/Contents/MacOS"
RESOURCES_DIR="$APP_BUNDLE/Contents/Resources"
PAYLOAD_DIR="$RESOURCES_DIR/app"
BUILD_TMP="$ROOT_DIR/.macos-build"
DMG_ROOT="$BUILD_TMP/dmg-root"
VERSION_FILE="$ROOT_DIR/VERSION"
DEFAULT_VERSION="$(date +%Y.%m.%d)"
if [[ -f "$VERSION_FILE" ]]; then
  DEFAULT_VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"
fi
VERSION="${ODYSSEUS_VERSION:-$DEFAULT_VERSION}"
DMG_PATH="$DIST_DIR/${APP_NAME}-macOS-${VERSION}.dmg"

echo "============================================================"
echo " Building $APP_NAME macOS distribution"
echo " Version: $VERSION"
echo " Root:    $ROOT_DIR"
echo " Output:  $APP_BUNDLE"
echo " DMG:     $DMG_PATH"
echo "============================================================"

if ! command -v hdiutil >/dev/null 2>&1; then
  echo "error: hdiutil is required and was not found" >&2
  exit 1
fi

mkdir -p "$DIST_DIR"
rm -rf "$APP_BUNDLE" "$BUILD_TMP" "$DMG_PATH"
mkdir -p "$BUILD_TMP"

echo "Creating app shell"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR" "$PAYLOAD_DIR"
cat > "$MACOS_DIR/$APP_NAME" <<'LAUNCHER'
#!/usr/bin/env bash
set -euo pipefail
APP_CONTENTS="$(cd "$(dirname "$0")/.." && pwd)"
exec "$APP_CONTENTS/Resources/launcher.sh" >/tmp/odysseus-launcher.log 2>&1
LAUNCHER
chmod +x "$MACOS_DIR/$APP_NAME"

cat > "$APP_BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
</dict>
</plist>
PLIST

cp "$ROOT_DIR/scripts/macos_launcher.sh" "$RESOURCES_DIR/launcher.sh"
chmod +x "$RESOURCES_DIR/launcher.sh"

if [[ -f "$ROOT_DIR/assets/Odysseus.icns" ]]; then
  cp "$ROOT_DIR/assets/Odysseus.icns" "$RESOURCES_DIR/Odysseus.icns"
  cp "$ROOT_DIR/assets/Odysseus.icns" "$RESOURCES_DIR/applet.icns"
elif [[ -f "$ROOT_DIR/build/Odysseus-boat.icns" ]]; then
  cp "$ROOT_DIR/build/Odysseus-boat.icns" "$RESOURCES_DIR/Odysseus.icns"
  cp "$ROOT_DIR/build/Odysseus-boat.icns" "$RESOURCES_DIR/applet.icns"
elif [[ -f "$ROOT_DIR/dist/Odysseus.app/Contents/Resources/Odysseus.icns" ]]; then
  cp "$ROOT_DIR/dist/Odysseus.app/Contents/Resources/Odysseus.icns" "$RESOURCES_DIR/Odysseus.icns"
  cp "$ROOT_DIR/dist/Odysseus.app/Contents/Resources/Odysseus.icns" "$RESOURCES_DIR/applet.icns"
fi

echo "Writing app metadata"
plist_set() {
  local key="$1"
  local type="$2"
  local value="$3"
  /usr/libexec/PlistBuddy -c "Set :$key $value" "$APP_BUNDLE/Contents/Info.plist" >/dev/null 2>&1 || \
    /usr/libexec/PlistBuddy -c "Add :$key $type $value" "$APP_BUNDLE/Contents/Info.plist" >/dev/null
}

plist_set "CFBundleName" "string" "$APP_NAME"
plist_set "CFBundleDisplayName" "string" "$APP_NAME"
plist_set "CFBundleIdentifier" "string" "$BUNDLE_ID"
plist_set "CFBundleExecutable" "string" "$APP_NAME"
plist_set "CFBundleVersion" "string" "$VERSION"
plist_set "CFBundleShortVersionString" "string" "$VERSION"
plist_set "CFBundleIconFile" "string" "Odysseus"
plist_set "CFBundleIconName" "string" "Odysseus"
plist_set "OSAAppletShowStartupScreen" "bool" "false"

echo "Copying app payload"
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
  --exclude '.macos-build/' \
  --exclude '.pytest_cache/' \
  --exclude '__pycache__/' \
  --exclude 'src/cache/' \
  --exclude 'docs/FIX_REPORT_*.md' \
  --exclude '*.pyc' \
  --exclude 'Deep-Live-Cam/' \
  --exclude 'Deep-Live-Cam.app/' \
  --exclude 'voice_changer_app/' \
  --exclude 'virtual-cam-bypass-extension/' \
  --exclude 'VoiceChanger.spec' \
  --exclude 'build_app.sh' \
  --exclude 'desktop_launcher.py' \
  --exclude 'run_deep_live_cam.sh' \
  --exclude 'run_voice_changer.sh' \
  --exclude 'tests/' \
  --exclude 'docker/' \
  --exclude 'Dockerfile' \
  "$ROOT_DIR"/ "$PAYLOAD_DIR"/

cat > "$RESOURCES_DIR/README-FIRST-RUN.txt" <<'README'
Odysseus for macOS

Drag Odysseus.app to Applications, then open it.

First launch:
- Odysseus copies its app files to ~/Library/Application Support/Odysseus/app
- It creates a private Python virtual environment at ~/Library/Application Support/Odysseus/.venv
- It installs Python dependencies from requirements.txt
- Your data is stored under ~/Library/Application Support/Odysseus/app/data

Requirement:
- Python 3.11 or newer must be installed for the first launch bootstrap.

Logs:
- ~/Library/Application Support/Odysseus/logs/bootstrap.log
- ~/Library/Application Support/Odysseus/logs/odysseus_desktop.log
README

echo "Ad-hoc signing app"
codesign --force --deep --sign - "$APP_BUNDLE" >/dev/null 2>&1 || true

echo "Creating DMG"
mkdir -p "$DMG_ROOT"
cp -R "$APP_BUNDLE" "$DMG_ROOT/"
ln -s /Applications "$DMG_ROOT/Applications"
hdiutil create -volname "$APP_NAME" -srcfolder "$DMG_ROOT" -ov -format UDZO "$DMG_PATH" >/dev/null

echo "============================================================"
echo " Done"
echo " App: $APP_BUNDLE"
echo " DMG: $DMG_PATH"
echo "============================================================"
