# Hướng Dẫn Sử Dụng Odysseus macOS

Tài liệu này dành cho bản Odysseus macOS: app tự chạy trên máy, dữ liệu ưu tiên lưu local, có thể dùng model local qua LM Studio hoặc model API qua provider như GateCheap/OpenAI-compatible.

## 1. Cài đặt và mở app

1. Tải file `.dmg` từ trang GitHub Releases.
2. Mở `.dmg`, kéo `Odysseus.app` vào `Applications`.
3. Mở `Odysseus.app`.
4. Lần chạy đầu app sẽ tạo môi trường riêng trong:

```text
~/Library/Application Support/Odysseus
```

Nếu macOS hỏi quyền truy cập file/thư mục, hãy cấp quyền cho Odysseus nếu bạn muốn Agent có thể đọc/ghi file ngoài workspace.

## 2. Tài khoản, tên user và mật khẩu

Vào `Settings` -> `Account`.

- `Save Username`: đổi tên user hiển thị và chủ sở hữu dữ liệu.
- `Set Password`: đặt mật khẩu cho app macOS local. Ở chế độ desktop-local, app cho phép set mật khẩu mới mà không cần biết mật khẩu tạm được tạo lúc bootstrap.
- `Change Password`: khi chạy bản web/server thông thường, bạn cần nhập mật khẩu hiện tại.
- `Two-Factor Authentication`: bật 2FA khi bạn dùng Odysseus trên mạng nội bộ hoặc server.

Sau khi đổi username hoặc mật khẩu, nếu app còn tab/cửa sổ cũ, hãy đóng mở lại app để mọi session hiển thị đồng bộ.

## 3. Thêm model

Vào `Settings` -> `Add Models`.

### Dùng LM Studio local

1. Mở LM Studio.
2. Vào `Developer` -> `Local Server`.
3. Bật server, thường là:

```text
http://127.0.0.1:1234
```

4. Trong Odysseus, thêm endpoint OpenAI-compatible trỏ tới địa chỉ đó.
5. Chọn model trong sidebar hoặc ô chọn model ở khung chat.

### Dùng GateCheap hoặc API OpenAI-compatible

1. Thêm endpoint API.
2. Base URL ví dụ:

```text
https://gatecheap.io.vn/v1
```

3. Dán API key.
4. Pin/cài model muốn dùng, ví dụ:

```text
deepseek-v4-flash-free
deepseek-v4-flash-search
claude-haiku-4-5
deepseek-v4-flash
```

Nếu một model trả `400` hoặc `500`, đó thường là lỗi provider/model đang không nhận request. Hãy thử model khác hoặc kiểm tra lịch sử request trên dashboard provider.

## 4. Chat, Agent, Odysseus và Hermes

- `Chat`: chỉ trả lời trong hội thoại, ít dùng tool.
- `Agent`: được phép dùng tool như đọc/ghi file, tạo tài liệu, chạy tác vụ.
- `Odysseus`: mode chính của app, ưu tiên luồng local-first và tool nội bộ.
- `Hermes`: mode thử nghiệm qua gateway agent khác. Chỉ nên dùng khi bạn muốn test luồng agent thay thế.

Khi muốn app tạo file ra Desktop, hãy dùng `Agent` và đảm bảo quyền file access đã được cấp trong Settings hoặc trong popup quyền của hệ thống.

## 5. Quyền truy cập file cho Agent

Vào `Settings` -> `AI Defaults` hoặc phần Agent/File Access.

Các mức quyền thường dùng:

- `Restricted`: an toàn nhất, chỉ trong vùng app/workspace.
- `User folders`: cho phép thư mục người dùng như Desktop/Documents/Downloads.
- `Home`: cho phép nhiều hơn trong home folder.
- `Full`: rộng nhất, chỉ dùng khi bạn tin model và task.

Nếu task cần xuất game ra Desktop, chọn ít nhất `User folders`, sau đó yêu cầu rõ đường dẫn, ví dụ:

```text
Tạo game HTML và lưu vào /Users/<ten-user>/Desktop/flappy/index.html
```

## 6. Email

Vào `Settings` -> `Email`.

1. Thêm email account.
2. Với Gmail/iCloud/Yahoo, dùng App Password, không dùng mật khẩu đăng nhập thường.
3. Bật IMAP/SMTP đúng host/port.
4. Bấm `Test` trước khi dùng AI draft/send.

Nếu email fail, nguyên nhân phổ biến là chưa có App Password, sai port, hoặc provider chặn đăng nhập bằng mật khẩu thường.

## 7. Lịch sử chat và dữ liệu

Lịch sử chat, config, model, email và dữ liệu local nằm trong:

```text
~/Library/Application Support/Odysseus/app/data
```

Không xóa thư mục này nếu bạn muốn giữ lịch sử. Khi cập nhật app, chỉ thay `Odysseus.app` trong `Applications`; dữ liệu trong Application Support vẫn được giữ.

## 8. Khắc phục nhanh

- App đứng nhưng model vẫn chạy: đóng Odysseus, mở lại app. Nếu cần, tắt tiến trình Python/Odysseus cũ trong Activity Monitor.
- Nút không bấm được: reload app hoặc mở lại; kiểm tra `/api/auth/status` có authenticated hay không.
- Mất model/API: vào `Settings` -> `Add Models`, kiểm tra endpoint và pinned models.
- Model chọn DeepSeek nhưng trả bằng model khác: tắt fallback mặc định hoặc chọn đúng model trong session mới.
- Không xuất được file ra Desktop: tăng file access mode lên `User folders` hoặc `Home`.

## 9. Cập nhật app

1. Tải `.dmg` mới.
2. Thoát Odysseus đang chạy.
3. Kéo app mới vào `Applications` và chọn Replace.
4. Mở lại app.

Dữ liệu người dùng không nằm trong bundle app, nên update app không làm mất lịch sử chat nếu bạn không xóa `~/Library/Application Support/Odysseus`.
