# Báo cáo fix Odysseus — 2026-06-07

Lưu lại để tiếp tục sau khi restart Claude Code. Repo: `/Users/rowiz/Documents/antigravity/epic-bell`

## Bối cảnh / nguồn lỗi
- User quay video `~/Desktop/Ghi Màn hình 2026-06-07 lúc 18.55.21.mov` báo "lỗi".
- Phân tích video bằng OCR (Vision của macOS, vì không có tesseract/pytesseract). Không phải crash — là lỗi hành vi + lỗi UI.
- 2 DB liên quan:
  - Repo (chạy từ source): `data/app.db`, key mã hóa `data/.app_key`
  - **Bản app đã build (user dùng)**: `/Users/rowiz/Library/Application Support/Odysseus/app/data/app.db`, key `.../app/data/.app_key`
  - Built app serve static + routes RIÊNG (bản copy), frontend giống hệt repo (đã `diff -q` xác nhận). **Mỗi lần sửa repo phải copy sang built app.**
- Auth: `AUTH_ENABLED` mặc định true. Để debug local đã chạy `AUTH_ENABLED=false APP_PORT=7860 uvicorn app:app`.
- Provider GateCheap: `https://gatecheap.io.vn/v1` (OpenAI-compatible). Key: sk-f30...c43291 (ĐÃ LỘ TRONG CHAT — nên rotate).

## Đã làm xong (3 nhóm)

### 1. Prompt-bloat (agent không chịu làm task) — `src/agent_loop.py`
- Triệu chứng: model local qwen3.5 cứ hỏi lại "bạn muốn làm gì cụ thể?" thay vì hành động khi user nói "làm đi"/"tiếp tục".
- Nguyên nhân: `_AGENT_RULES` (~1668 tok) và `_API_AGENT_RULES` (~3346 tok) gửi full mọi request, nhồi rules email/calendar/cookbook lấn át chỉ thị hành động.
- Fix:
  - Thêm chỉ thị "ACT, DON'T NARRATE" (xử lý follow-up ngắn/mơ hồ) vào cả 2 khối rules.
  - Gate rules theo tool đã chọn (`_gate_rules`, `_FENCED_RULE_GATES`, `_API_RULE_GATES`, các nhóm `_RG_*`). Chỉ áp dụng ở nhánh RAG (`relevant_tools` đã lọc nhỏ), nhánh fallback giữ full.
  - Self-test lúc import `_verify_rule_gates()` đảm bảo gate với đủ tool -> tái dựng byte-identical (model lớn không đổi hành vi).
  - Coding request: fenced ~1792->562 tok, API ~3410->407 tok.
- Test: thêm class `TestRuleGating` trong `tests/test_agent_loop.py` (7 test).

### 2. Data GateCheap + sessions kẹt
- Test 15 model gatecheap: **10 chạy**, **5 hỏng** (lỗi phía provider):
  - OK: claude-sonnet-4.6, claude-opus-4-8/4-7/4-6, claude-haiku-4-5, gpt-5.5, gpt-5.4, gemini-3.1-pro, gemini-3.5-flash, gemini-3-flash
  - HỎNG: gpt-5.2 (404), deepseek-v4-pro (400), deepseek-v4-flash (400), deepseek-v4-flash-search (500), deepseek-v4-flash-free (500)
- Đã sửa CẢ 2 DB:
  - Cập nhật api_key mới (mã hóa Fernet bằng `.app_key` tương ứng, verify decrypt round-trip OK).
  - `cached_models`/`pinned_models` = 10 model OK; `hidden_models` = 5 model hỏng.
  - `model_refresh_mode='auto'`, `is_enabled=1`, `supports_tools=1`.
  - 2 session kẹt ở `deepseek-v4-flash` (gây không chat được) -> chuyển sang `claude-sonnet-4.6`: id `42673f35-76df-4062-8106-ec0f00e31537`, `9f14608f-2d7e-4d70-ae7c-29a41be2c9c8`.
- Đã backup DB trước khi sửa (`*.bak-<timestamp>`).

### 3. Lỗi NHẤP NHÁY model picker (2 bug code thật)
- **Bug A — probe quá gắt, không hysteresis**: picker ping local endpoint mỗi 5s, timeout 1.5s. LM Studio bận serve qwen3.5-122b (122B) -> trả lời >1.5s -> bị mark offline (mờ) -> ping sau OK -> sáng lại -> CHỚP TẮT.
- **Bug B — phân loại sai**: `localhost:1234` (LM Studio) bị xếp "api/proxy" thay vì "local" vì có api_key + path `/v1`.
- Fix:
  - `routes/model_routes.py`:
    - `_probe_one` timeout 1.5s -> **3.5s**.
    - `_classify_endpoint`: địa chỉ local/private/tailscale **luôn** = "local", đè heuristic proxy (check host trước).
  - `static/js/modelPicker.js`: thêm hysteresis `_PROBE_FAIL_THRESHOLD=2` (fail 2 lần liên tiếp mới offline, success reset ngay) trong `_refreshLocalProbe`.
- Verify chạy app thật: probe-local giờ báo LM Studio `alive=true, 8ms` đúng.
- Test: thêm 5 test classification trong `tests/test_model_routes.py` (`TestClassifyEndpoint`).

## Trạng thái hiện tại
- **282/282 test pass.** Python compile sạch, JS `node --check` OK.
- Files đã sửa (working tree, **CHƯA COMMIT**):
  - `routes/model_routes.py`
  - `src/agent_loop.py`
  - `static/js/modelPicker.js`
  - `tests/test_agent_loop.py`
  - `tests/test_model_routes.py`
- **Đã sync sang built app** (`.../Odysseus/app/`): `model_routes.py`, `modelPicker.js`, `agent_loop.py`. (Nếu sửa thêm nhớ sync lại.)
- Dev server trên 7860 đã tắt.

## Việc cần làm tiếp (TODO khi mở lại)
1. User restart Odysseus (đóng hẳn rồi mở) để nạp code mới -> kiểm tra picker còn nhấp nháy không.
2. Nếu vẫn nhấp nháy: chưa chứng kiến trực tiếp được (browser MCP cần bấm Connect thủ công). Cân nhắc:
   - Kiểm tra các `setInterval` khác: `app.js:3537` rail sync 1s, `modalManager.js:1413` scan 1s, `chat.js` probe-during-stream 10s.
   - Kiểm tra `initModelPickerResponsive` (app.js ~2069): class `.picker-auto-hidden` được toggle nhưng KHÔNG có CSS rule (vô hại, nhưng đáng dọn).
   - Cân nhắc skip probe khi đang stream cho chính endpoint đó.
3. Hỏi user có muốn commit gọn thành 1-2 commit không (chưa commit theo nguyên tắc).
4. Nhắc user rotate API key gatecheap (đã lộ trong chat).
5. Tránh dùng model deepseek/gpt-5.2 (hỏng phía gatecheap) — dùng claude/gpt-5.5/gemini.

## Lệnh hữu ích
    # chạy dev server debug
    source .venv311/bin/activate
    AUTH_ENABLED=false APP_PORT=7860 python -m uvicorn app:app --host 127.0.0.1 --port 7860

    # test
    python -m pytest -q

    # DB built app
    sqlite3 "/Users/rowiz/Library/Application Support/Odysseus/app/data/app.db" "SELECT id,name,base_url,model_refresh_mode FROM model_endpoints;"

    # sync repo -> built app sau khi sửa
    APPDIR="/Users/rowiz/Library/Application Support/Odysseus/app"
    cp routes/model_routes.py "$APPDIR/routes/"; cp static/js/modelPicker.js "$APPDIR/static/js/"; cp src/agent_loop.py "$APPDIR/src/"
