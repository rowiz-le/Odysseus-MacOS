# Báo cáo fix Odysseus — 2026-06-08

Lưu lại để tiếp tục sau khi restart Claude Code. Repo: `/Users/rowiz/Documents/antigravity/epic-bell`

## Bối cảnh / nguồn lỗi

User quay video `~/Desktop/Ghi Màn hình 2026-06-08 lúc 11.49.40.mov` báo lỗi model picker đóng/mở nhanh, không thể switch model.

- App chạy từ: `/Users/rowiz/Library/Application Support/Odysseus/app/`
- Launcher: `odysseus_desktop_launcher.py` → uvicorn port **7001**, dùng venv tại `.../Odysseus/.venv/`
- Webview: pywebview (WKWebView / WebKit on macOS)
- Static files: `_RevalidatingStatic` với `Cache-Control: no-cache` cho .js/.css/.html
- Cache-bust: `?v=...` trong `index.html`

## Nguyên nhân thật sự

**Không phải endpoint-dimming flicker** (đã fix ở 2026-06-07). Đây là bug khác:

1. **Bản app build vẫn còn code cũ** — báo cáo 06-07 ghi "đã sync" nhưng thực tế 2 file picker chưa được copy sang built app. Kiểm tra md5 xác nhận sự khác biệt.
2. **Code cũ** (`modelPicker.js` trước fix) có:
   - `row.addEventListener('click', () => _pick(m))` — **không có `stopPropagation`** → click bubble lên, picker đóng ngay sau khi mở
   - `_LOCAL_PROBE_TTL_MS = 5000` → probe mỗi 5s re-render list kể cả khi picker đang closing
   - Không exclude `#model-picker-menu` trong outside-click handler (`sessions.js`)
3. **WebKit cache** trong `~/Library/WebKit/python/` giữ bản JS cũ ngay cả sau khi file đã đúng.

## Đã làm (06-08)

### 1. Sync file đúng sang app
- `static/js/modelPicker.js` → `app/static/js/modelPicker.js` (md5 MATCH)
- `static/js/sessions.js` → `app/static/js/sessions.js` (md5 MATCH)

### 2. Bump cache-bust version (`20260606fix2` → `20260608fix3`)
Sửa trong cả repo và app `static/index.html`:
```
?v=20260608fix3
```
Áp dụng cho: `app.js`, `sessions.js`, `init.js` (và preload hints).

### 3. Thêm version string vào import `modelPicker.js` trong `sessions.js`
```js
// trước:
import { initModelPicker, updateModelPicker } from './modelPicker.js';
// sau:
import { initModelPicker, updateModelPicker } from './modelPicker.js?v=20260608fix3';
```
Đảm bảo WKWebView không cache module này độc lập.

### 4. Xóa WebKit cache
```bash
rm -rf ~/Library/WebKit/python
```
Cache này (4KB, dùng bởi pywebview / com.apple.python3) giữ bản JS cũ.

### 5. Verify live server
Curl port 7001 xác nhận server đang phục vụ code đã fix (hysteresis + stopPropagation markers hiện diện).

## Trạng thái hiện tại

- **282/282 test pass** (từ session trước, chưa có test mới hôm nay).
- Files đã sửa (working tree, **CHƯA COMMIT**):
  - `static/index.html` (version bump)
  - `static/js/sessions.js` (version bump trong import modelPicker)
  - `routes/model_routes.py` (từ 06-07)
  - `src/agent_loop.py` (từ 06-07)
  - `static/js/modelPicker.js` (từ 06-07)
  - `tests/test_agent_loop.py` (từ 06-07)
  - `tests/test_model_routes.py` (từ 06-07)
- **Đã sync sang built app**: `modelPicker.js`, `sessions.js`, `index.html` (md5 confirmed)
- WebKit cache đã xóa.

## Việc cần làm tiếp (TODO khi mở lại)

1. **User đóng hẳn Odysseus rồi mở lại** → webview load lại JS mới (version `fix3`, WebKit cache trống).
2. Kiểm tra picker còn lỗi không. Nếu vẫn còn:
   - Mở DevTools trong pywebview (nếu được): kiểm tra JS console errors
   - Kiểm tra `app.js` dòng `closeAllPopups` có trigger không khi click
   - Xem log lúc bấm: `tail -f "/Users/rowiz/Library/Application Support/Odysseus/app/logs/odysseus-app.log"`
3. **Gom commit**: tất cả thay đổi từ 06-07 + 06-08 chưa commit.
   ```bash
   cd /Users/rowiz/Documents/antigravity/epic-bell
   git add routes/model_routes.py src/agent_loop.py \
     static/js/modelPicker.js static/js/sessions.js \
     static/index.html \
     tests/test_agent_loop.py tests/test_model_routes.py
   git commit -m "fix: model picker close race, prompt-bloat gates, endpoint flicker"
   ```
4. **Nhắc user rotate API key GateCheap** (đã lộ trong chat cũ).
5. Tránh dùng model deepseek/gpt-5.2 (hỏng phía gatecheap).

## Thông tin kỹ thuật quan trọng

```
App dir:      /Users/rowiz/Library/Application Support/Odysseus/app/
App venv:     /Users/rowiz/Library/Application Support/Odysseus/.venv/
Port:         7001 (desktop launcher), 8100 (chroma), 8642 (hermes)
DB repo:      data/app.db   key: data/.app_key
DB app:       app/data/app.db  key: app/data/.app_key
```

### Lệnh hữu ích
```bash
# chạy dev server debug (repo, port 7860)
source .venv311/bin/activate
AUTH_ENABLED=false APP_PORT=7860 python -m uvicorn app:app --host 127.0.0.1 --port 7860

# test
python -m pytest -q

# sync repo → built app sau khi sửa
APPDIR="/Users/rowiz/Library/Application Support/Odysseus/app"
cp static/js/modelPicker.js "$APPDIR/static/js/"
cp static/js/sessions.js "$APPDIR/static/js/"
cp static/index.html "$APPDIR/static/"
cp routes/model_routes.py "$APPDIR/routes/"
cp src/agent_loop.py "$APPDIR/src/"

# verify md5
md5 static/js/modelPicker.js "$APPDIR/static/js/modelPicker.js"
md5 static/js/sessions.js "$APPDIR/static/js/sessions.js"
md5 static/index.html "$APPDIR/static/index.html"
```
