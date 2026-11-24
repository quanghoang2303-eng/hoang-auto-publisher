> **Tài liệu V2 cũ.** Bản V3 hiện đăng tập đầy đủ lên cả Facebook Page và YouTube. Xem `HUONG_DAN_V3_VIDEO_DAI_VA_HIGHLIGHT.md` để cấu hình chính xác.

# Hướng dẫn bật tự động đăng video YouTube dài (MacBook)

Phiên bản này giữ nguyên luồng Facebook Reels / YouTube Shorts / TikTok (nếu bạn đã bật TikTok), đồng thời bổ sung hàng đợi **YouTube video dài** độc lập.

## 1. Nâng cấp an toàn

1. Tạm dừng job `launchd` cũ trước khi thay code, để không thay mã khi chương trình đang đăng video.
2. Sao lưu thư mục `state/`, file `.env`, `token.json`, `client_secret.json` đang dùng trên MacBook. **Không** đăng những file này lên GitHub.
3. Giải nén ZIP mới và cập nhật các file `.py`, `README.md`, `requirements.txt` trong thư mục ứng dụng cũ. Giữ nguyên `.env`, `state/` và token hiện tại.
4. Trong file `.env` cũ, thêm các dòng ở phần 2. Không thay thế toàn bộ `.env` bằng `.env.example`.
5. Mở lại lịch `launchd` sau khi chạy kiểm tra `scan` và `preview`.

Nếu chưa từng cài MVP trên MacBook, đọc phần **Install on the Mac** trong `README.md` trước.

## 2. Cấu hình `.env`

```ini
# Luồng Shorts cũ — giữ nguyên theo nhu cầu của bạn
VIDEO_DIR=/Users/TEN_MACBOOK/Videos/AutoPublisher/inbox
POST_TIMES=09:00,12:00,18:00
MAX_DAILY_POSTS=3
PLATFORMS=facebook,youtube

# Luồng YouTube video dài — mới
YT_LONG_VIDEO_DIR=/Users/TEN_MACBOOK/Videos/AutoPublisher/youtube_long
YT_LONG_POST_TIMES=19:00
YT_LONG_POST_DAYS=mon,wed,fri
YT_LONG_MAX_DAILY_POSTS=1
YT_LONG_PRIVACY=private
YT_LONG_CATEGORY_ID=27

TIMEZONE=Asia/Ho_Chi_Minh
ENABLE_LIVE_POSTING=false
```

- Thay `TEN_MACBOOK` bằng tên thư mục người dùng macOS thực tế; có thể xem bằng lệnh `whoami` trong Terminal.
- `YT_LONG_POST_DAYS=mon,wed,fri`: đăng vào thứ Hai, Tư, Sáu. Để trống nếu muốn đăng mọi ngày.
- `YT_LONG_PRIVACY=private`: dùng trong giai đoạn kiểm thử. Đổi thành `public` khi đã kiểm tra thành công và muốn tự động công khai không cần xác nhận.
- Giữ `ENABLE_LIVE_POSTING=false` cho đến khi đã kiểm tra xong.
- Không cần xin thêm Google OAuth scope; phần đăng video dài dùng lại `youtube.upload` và token YouTube hiện tại.

## 3. Bỏ video vào thư mục

```text
Videos/AutoPublisher/
  inbox/                 <- Shorts/Reels (4–60 giây, dọc 9:16)
  youtube_long/          <- YouTube dài (nên dùng ngang 16:9)
    generation_tap_01.mp4
    generation_tap_01.txt
    generation_tap_01.json
```

`generation_tap_01.txt` có thể chứa tóm tắt hoặc lời thoại để AI hiểu nội dung tập phim. Không tự động chuyển lời nói thành chữ.

Bạn có thể tạo `generation_tap_01.json` với tiêu đề, mô tả chính xác để không cần AI đoán nội dung:

```json
{
  "youtube_title": "GENERATION - Tập 01 | Học cách dẫn dắt AI",
  "youtube_description": "Series hoạt hình GENERATION - Đừng chỉ học cách dùng AI. Hãy học cách dẫn dắt AI.",
  "youtube_made_for_kids": true
}
```

Trường `youtube_made_for_kids` cần xác nhận phù hợp với đối tượng thực tế của **từng video**. Không nên tự mặc định mọi video hoạt hình là dành cho trẻ em.

## 4. Kiểm tra an toàn trước khi bật đăng tự động

Trong Terminal, mở thư mục dự án đã cài và kích hoạt `.venv` như hướng dẫn cài đặt, rồi chạy:

```bash
python publisher.py scan
python publisher.py preview --stream long
python publisher.py preview --stream short
python publisher.py status
python -m unittest discover -s tests -v
```

`preview` không đăng bài. Nếu đầu ra cho `--stream long` có `Platforms: ['youtube']` thì đã tách đúng luồng, không gửi video dài lên Facebook/TikTok.

Để đăng thử một tập dài ở chế độ riêng tư:

1. Kiểm tra `.env`: `YT_LONG_PRIVACY=private`.
2. Chuyển `ENABLE_LIVE_POSTING=true`.
3. Chạy:

```bash
python publisher.py run-now --stream long
python publisher.py status
```

4. Vào **YouTube Studio → Content** để kiểm tra video đã upload/được xử lý xong.
5. Sau khi test thành công, chỉnh `YT_LONG_PRIVACY=public` để video dài tương lai được gửi ở chế độ công khai.

> Lưu ý: `submitted` nghĩa là YouTube đã nhận upload, chưa bảo đảm đã xử lý xong hoặc người khác xem được. Nếu xuất hiện `needs_check`, hãy kiểm tra YouTube Studio trước khi làm lại để tránh đăng trùng.

## 5. Tự động lịch đăng trên MacBook

Job `launchd` cũ đã gọi `publisher.py tick` mỗi 5 phút; phiên bản mới sẽ kiểm tra cả hai luồng trong cùng một lần chạy. Không cần tạo thêm job. Mac phải đang thức và có Internet trong cửa sổ đăng bài. Không di chuyển hoặc đổi video đã vào hàng đợi trước khi hoàn tất.

Nếu video dài trên 15 phút, hãy xác minh tính năng tải video dài của kênh YouTube tại [YouTube Studio → Feature eligibility](https://www.youtube.com/features). Quy định hiện tại của YouTube giới hạn video tối đa 12 giờ hoặc 256 GB, tùy điều kiện nào đến trước.

## 6. Các việc chưa tự động hóa

- Thumbnail tùy chỉnh, playlist, chapter/timestamp và transcript tự động **chưa** được triển khai trong MVP.
- Sau khi ứng dụng mất kết nối giữa lúc upload và không thể xác định kết quả, trạng thái là `needs_check`. MVP không tự đăng lại vì có nguy cơ tạo bản sao video.
- API TikTok hoặc macro Android cần quyền và điều kiện riêng; bật YouTube dài không làm thay đổi điều kiện đăng TikTok.