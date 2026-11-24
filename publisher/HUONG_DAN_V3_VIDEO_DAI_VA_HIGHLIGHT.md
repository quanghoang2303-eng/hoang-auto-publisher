# Hoang Auto Publisher V3 — Hướng dẫn tập đầy đủ & highlight

## Mục tiêu

- **Full Episodes / tập phim đầy đủ:** 1 file MP4 → YouTube Video thông thường + Facebook Page Video (mỗi nền tảng một trạng thái riêng).
- **Highlights / trích đoạn:** các file MP4 dọc 9:16 → YouTube Shorts + Facebook Page Reels (+ TikTok nếu đã cấu hình).
- Lịch phát hành **hai nhánh độc lập**; không gửi tập 8 phút lên nhánh TikTok/Shorts.
- AI có thể tạo title/caption dựa trên tên file, 3 khung hình và nội dung `.txt`; **chưa tự chọn hoặc cắt highlight** từ phim dài. Các highlight cần được xuất ra file MP4 riêng trước.

**Lưu ý Facebook năm 2025–2026:** Meta đã hợp nhất video thành Reels bất kể thời lượng. Workflow vẫn đăng đúng file đầy đủ / trích đoạn, nhưng cách Facebook gắn nhãn hiển thị do nền tảng quyết định. Tài liệu: https://about.fb.com/news/2025/06/making-it-easier-create-videos-on-facebook/.

## A. Cài đặt không mất dữ liệu V2

1. Dừng chương trình/lịch `launchd` phiên V2 trước khi nâng cấp.
2. Sao lưu `.env`, `state/publisher.sqlite3`, `token.json` và `client_secret.json` ra thư mục **không public**. KHÔNG upload các file này lên GitHub.
3. Giải nén ZIP V3, chép phần code (`publisher.py`, `backends.py`, `tests/`, tài liệu) vào **đúng thư mục chương trình Python**, không phải GitHub repo chứa website OAuth.
4. Không chép đè `.env` và `state/` cũ. Giữ token hiện có. SQLite được nâng cấp bằng cách thêm cột còn thiếu; dữ liệu, fingerprint và hàng đợi cũ được giữ nguyên. Không xóa cơ sở dữ liệu, không thay token hay thông tin đăng nhập.
5. Bổ sung phần B vào `.env`, chạy `scan`, `preview`, `status` trước khi bật live. Các lệnh này không đăng bài.
6. Lịch V2 có thể dùng lại `YT_LONG_VIDEO_DIR`, `YT_LONG_POST_TIMES`, `YT_LONG_POST_DAYS`, `YT_LONG_MAX_DAILY_POSTS`; cấu hình `FULL_*` mới được ưu tiên khi có.
7. Các full-episode job đã tạo từ V2 vẫn chỉ có YouTube: **V3 không âm thầm đăng Facebook cho lịch sử cũ**. Tập tiếp theo được lập lịch bằng `FULL_PLATFORMS` mới.

## B. Cấu hình `.env`

```ini
TIMEZONE=Asia/Ho_Chi_Minh
# Highlight dọc 9:16, 4–60 giây
VIDEO_DIR=/Users/TEN_MACBOOK/Videos/AutoPublisher/highlights
PLATFORMS=facebook,youtube
POST_TIMES=12:00,20:00
MAX_DAILY_POSTS=2

# Tập đầy đủ, thường 16:9, ví dụ 8 phút
FULL_VIDEO_DIR=/Users/TEN_MACBOOK/Videos/AutoPublisher/full_episodes
FULL_PLATFORMS=facebook,youtube
FULL_POST_TIMES=19:00
FULL_POST_DAYS=mon,wed,fri
FULL_MAX_DAILY_POSTS=1

FB_GRAPH_VERSION=v27.0
FB_PAGE_ID=ID_FANPAGE
FB_PAGE_ACCESS_TOKEN=TOKEN_TRONG_MAY_KHONG_CHIA_SE
# Facebook luôn đăng công khai; cần bật riêng cả hai cờ mới đăng thật
FB_ALLOW_PUBLIC_POSTING=false
# Giới hạn an toàn và kích thước mỗi phần tải lên cho tập đầy đủ
FB_FULL_MAX_BYTES=1000000000
FB_FULL_MAX_DURATION_SECONDS=43200
FB_UPLOAD_CHUNK_BYTES=8388608
FB_VIDEO_UPLOAD_HOST=graph.facebook.com

YT_PRIVACY=private
YT_LONG_PRIVACY=private
YT_MADE_FOR_KIDS=
YT_LONG_CATEGORY_ID=27
ENABLE_LIVE_POSTING=false
# Để trống nếu không dùng manifest JSON tùy chọn
PUBLISH_MANIFEST=
TIKTOK_MODE=off
```

Thay `TEN_MACBOOK` bằng username thực. **Cùng một lịch `FULL_POST_TIMES` sẽ tạo hai tác vụ riêng** cho Facebook và YouTube; muốn đăng hai ngày/giờ hoàn toàn khác nhau sẽ cần tính năng offset per-platform, chưa có trong V3.

## C. Gắn metadata riêng cho hai nền tảng

Ví dụ:

```text
full_episodes/
  GENERATION_S01_E01.mp4
  GENERATION_S01_E01.json
  GENERATION_S01_E01.txt
highlights/
  GENERATION_S01_E01_H01.mp4
  GENERATION_S01_E01_H01.txt
  GENERATION_S01_E01_H02.mp4
```

Có thể dùng sidecar `.json` cạnh video để đặt metadata riêng, hoặc dùng manifest chung tùy chọn. Đây là ví dụ manifest cho một tập dài và một highlight:

```json
{
  "videos": [
    {
      "kind": "long",
      "episode_id": "GEN-S01-E01",
      "media_filename": "GENERATION_S01_E01.mp4",
      "allowed_targets": ["facebook", "youtube"],
      "platform_metadata": {
        "facebook": {"title": "GENERATION — Tập 01 đầy đủ", "description": "Cùng xem hành trình đầu tiên."},
        "youtube": {"title": "GENERATION | Tập 01", "description": "Tập đầy đủ số 01.", "category_id": 27, "made_for_kids": true}
      }
    },
    {
      "kind": "short",
      "episode_id": "GEN-S01-E01-H01",
      "media_filename": "GENERATION_S01_E01_H01.mp4",
      "allowed_targets": ["facebook", "youtube"],
      "platform_metadata": {
        "facebook": {"title": "GENERATION | Trích đoạn 01", "description": "Một đoạn ngắn từ tập 01."},
        "youtube": {"title": "GENERATION | Trích đoạn 01", "description": "Highlight của tập 01."}
      }
    }
  ]
}
```

Lưu JSON ở đường dẫn riêng rồi đặt `PUBLISH_MANIFEST=/duong/dan/manifest.json`. Mỗi mục cần `kind`, `episode_id` tường minh, `media_filename`, `allowed_targets` và metadata không rỗng cho từng nền tảng. Tên file phải khớp chính xác. Danh sách đích phải khớp chính xác `FULL_PLATFORMS` hoặc `PLATFORMS`. Khi để `PUBLISH_MANIFEST` trống, chương trình dùng sidecar, AI hoặc tên file như trước.

Đây là **ví dụ biên tập**, cần chỉnh lại theo nội dung tập đã render thực tế. Chọn `youtube_made_for_kids` sau khi đánh giá đối tượng nội dung theo chính sách YouTube; nếu không chắc, để trống trong `.env` và cấu hình metadata chính xác cho từng tập.

Có thể đặt bản tóm tắt hoặc transcript vào `.txt` để AI viết caption trung thực hơn. Nếu có `youtube_title` hoặc `youtube_description` trong JSON, cần cả hai trường. `facebook_title` và `facebook_description` là override riêng, có thể bỏ qua để dùng bản sao từ YouTube.

## D. Chạy kiểm thử

```bash
cd /duong/dan/drama-studio/publisher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Sửa VIDEO_DIR và FULL_VIDEO_DIR trong .env trước khi chạy:
python publisher.py scan
python publisher.py preview --stream long    # tập đầy đủ
python publisher.py preview --stream short   # highlight
python publisher.py status
```

Các lệnh này không tải video lên. Thử ngoại tuyến có thể chạy `python -m unittest discover -s tests -v`; bài thử dùng giả lập, không cần token và không đăng thật.

Khi đã kiểm tra tài khoản, token và nội dung, bật:

```ini
ENABLE_LIVE_POSTING=true
```

**ĐĂNG THẬT CÔNG KHAI:** lệnh sau gửi bài thật. Facebook cần cả `ENABLE_LIVE_POSTING=true` và `FB_ALLOW_PUBLIC_POSTING=true`; chỉ chạy sau khi chọn video an toàn:

```bash
python publisher.py run-now --stream long
```

Đầu tiên, nên để YouTube `YT_LONG_PRIVACY=private`. Facebook Page Videos và Reels đều công khai khi đăng; không có chế độ riêng tư Facebook trong cấu hình này. Hãy kiểm tra Page và YouTube Studio trước khi bật tự động `tick`.

Để chạy highlights sau đó:

**Lệnh này cũng đăng thật. Nếu có Facebook trong `PLATFORMS`, bài highlight sẽ được đăng công khai.**

```bash
python publisher.py run-now --stream short
```

Không có tính năng xem trước/đăng riêng tư Facebook Page video dài bằng biến `YT_LONG_PRIVACY` (biến này chỉ áp dụng cho YouTube).

## E. Lịch tự động và trạng thái

- `python publisher.py tick`: chạy hai nhánh theo giờ trong `.env`.
- Cài đúng một LaunchAgent cho dự án: `python install_launchd.py`, sau đó chạy lệnh `launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/local.macreelspublisher.plist"`. Xem hoạt động bằng `launchctl print gui/$(id -u)/local.macreelspublisher`. Job gọi `tick` mỗi 5 phút để xử lý cả hai nhánh; không cài hai lịch song song.
- Với Facebook tập đầy đủ, trạng thái `submitted` nghĩa là API đã nhận yêu cầu, chưa chắc đã hiển thị. Workflow có truy vấn trạng thái Facebook video dài; nếu Meta xác nhận, chuyển `published`.
- Với Facebook tập đầy đủ, mỗi phần đã nhận được lưu phiên và vị trí byte vào SQLite. Lỗi mạng hoặc máy chủ tạm thời khi gửi một phần sẽ thử lại đúng phần đó tối đa 3 lần (đổi bằng `FB_UPLOAD_CHUNK_RETRIES`, từ 0 đến 10); ứng dụng kiểm tra vị trí byte Meta trả về trước khi đi tiếp. Nếu hết số lần thử mà phiên còn byte chưa gửi, mục quay lại `queued`; lượt chạy lịch tiếp theo dùng lại đúng phiên và vị trí đã lưu. `FINISH` chỉ gửi một lần. Nếu phản hồi ở bước này không rõ, mục chuyển thành `needs_check`; hãy tự kiểm tra Page trước khi thử lại.
- Lỗi YouTube/Facebook không rõ kết quả cũng thành `needs_check` và không tự tạo bài thứ hai. `submitted` chỉ có nghĩa máy chủ nhận yêu cầu, chưa khẳng định bài đã công khai.
- Nếu file Facebook vượt `FB_FULL_MAX_BYTES` hoặc `FB_FULL_MAX_DURATION_SECONDS`, tác vụ bị chặn trước khi gửi.
- TikTok cần kiểm tra chế độ API hoặc ADB và quy định nền tảng; mặc định tắt.
- MacBook phải thức và có mạng tại khung giờ. Với video dài tải lên lâu, hai nền tảng có thể đăng lệch vài phút.

## F. API cần cấp quyền

- Facebook Page: Page ID + Page Access Token có quyền đăng video, `pages_manage_posts`, `pages_read_engagement` và Page task `CREATE_CONTENT`, cùng quyền ứng dụng phù hợp. Khi bật FULL_PLATFORMS có `facebook`, phải thử API `/page_id/videos` thực tế.
- YouTube: OAuth Desktop với scope `https://www.googleapis.com/auth/youtube.upload`; không cần API riêng cho video dài. Chạy `python publisher.py authorize-youtube` để cấp quyền. Token lưu trên máy và được làm mới khi còn hiệu lực; nếu quyền bị thu hồi/hết hạn, cấp quyền lại. `private` là riêng tư, `unlisted` xem được bằng liên kết, `public` ai cũng xem được. `YT_PRIVACY` điều khiển highlight; `YT_LONG_PRIVACY` điều khiển tập dài và mặc định là `private`.

Trước khi vận hành, tự xác nhận tên file, `scan`, nội dung `preview`, nền tảng và token đúng; xem `status` để xử lý mọi mục `needs_check`. Sau lần đăng thật có chủ đích, kiểm tra Page và YouTube Studio. Tài liệu API không xác nhận quyền trên tài khoản hoặc kết quả đăng thật; chỉ tài khoản của bạn mới kiểm chứng được.

## Giới hạn V3

- Chưa tự cắt highlight / chọn đoạn viral bằng AI.
- Tập Facebook dùng tải tiếp tục được và bị chặn theo giới hạn cấu hình (mặc định 1 GB, 12 giờ); kết quả không rõ ở bước kết thúc vẫn cần kiểm tra thủ công.
- Chưa có cách đảm bảo một video được nền tảng gắn nhãn 'video thường' thay vì 'Reels'.
- Chưa có cross-platform publication time offset hay dashboard web.
- Không có token thật trong ZIP, chưa test đăng thật với Fanpage/kênh YouTube của người dùng.
- **Repo GitHub Pages `hoang-auto-publisher` chỉ là website OAuth**, không nên thay các file `index.html`, `privacy.html`, `terms.html`, `styles.css` bằng source Python này.
