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
4. Không chép đè `.env` và `state/` cũ. Giữ token hiện có. Tạo thư mục video đầy đủ và highlight.
5. Bổ sung phần B vào `.env`, chạy test, `scan`, `preview` trước khi bật live.
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
# Multipart upload safety limit (không hỗ trợ chunked trên 1 GB trong V3)
FB_FULL_MAX_BYTES=1000000000
# Meta graph-video host cũ đã deprecate; giữ graph.facebook.com
FB_VIDEO_UPLOAD_HOST=graph.facebook.com

YT_PRIVACY=private
YT_LONG_PRIVACY=private
YT_MADE_FOR_KIDS=
YT_LONG_CATEGORY_ID=27
ENABLE_LIVE_POSTING=false
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

`GENERATION_S01_E01.json` có thể chứa:

```json
{
  "youtube_title": "GENERATION | Tập 01: Bíp và nhiệm vụ dọn phòng",
  "youtube_description": "Tập 01 của Biệt Đội AI Nhí. Đừng chỉ học cách dùng AI. Hãy học cách dẫn dắt AI.",
  "facebook_title": "GENERATION — Tập 01 đầy đủ",
  "facebook_description": "Cùng xem hành trình đầu tiên của Biệt Đội AI Nhí!",
  "youtube_made_for_kids": true
}
```

Đây là **ví dụ biên tập**, cần chỉnh lại theo nội dung tập đã render thực tế. Chọn `youtube_made_for_kids` sau khi đánh giá đối tượng nội dung theo chính sách YouTube; nếu không chắc, để trống trong `.env` và cấu hình metadata chính xác cho từng tập.

Có thể đặt bản tóm tắt hoặc transcript vào `.txt` để AI viết caption trung thực hơn. Nếu có `youtube_title` hoặc `youtube_description` trong JSON, cần cả hai trường. `facebook_title` và `facebook_description` là override riêng, có thể bỏ qua để dùng bản sao từ YouTube.

## D. Chạy kiểm thử

```bash
cd /duong/dan/mac-reels-publisher
source .venv/bin/activate
python -m unittest discover -s tests -v
python publisher.py scan
python publisher.py preview --stream long    # tập đầy đủ
python publisher.py preview --stream short   # highlight
python publisher.py status
```

Khi đã kiểm tra tài khoản, token và nội dung, bật:

```ini
ENABLE_LIVE_POSTING=true
```

**LƯU Ý: lệnh tiếp theo đăng thật lên các nền tảng đã bật**, không phải dry-run:

```bash
python publisher.py run-now --stream long
```

Đầu tiên, nên để YouTube `YT_LONG_PRIVACY=private`; Facebook API mặc định công khai, nên **chỉ dùng video thử nghiệm an toàn**. Hãy kiểm tra kết quả trên cả Page và YouTube Studio trước khi bật tự động `tick`.

Để chạy highlights sau đó:

```bash
python publisher.py run-now --stream short
```

Không có tính năng xem trước/đăng riêng tư Facebook Page video dài bằng biến `YT_LONG_PRIVACY` (biến này chỉ áp dụng cho YouTube).

## E. Lịch tự động và trạng thái

- `python publisher.py tick`: chạy hai nhánh theo giờ trong `.env`.
- Có thể dùng LaunchAgent hiện tại sau khi thay code; không cần chạy hai scheduler song song.
- Với Facebook tập đầy đủ, trạng thái `submitted` nghĩa là API đã nhận yêu cầu, chưa chắc đã hiển thị. Workflow có truy vấn trạng thái Facebook video dài; nếu Meta xác nhận, chuyển `published`.
- Nếu request timeout sau khi gửi, job được đánh dấu `needs_check` và **không tự đăng lại** để tránh trùng. Kiểm tra trong Page/Studio trước khi thao tác tiếp.
- Nếu file Facebook dài quá giới hạn configured, tác vụ `blocked` trước khi upload; nén lại hoặc nâng cấp upload chunked, không tăng giới hạn tùy tiện.
- TikTok cần kiểm tra chế độ API hoặc ADB và quy định nền tảng; mặc định tắt.
- MacBook phải thức và có mạng tại khung giờ. Với video dài tải lên lâu, hai nền tảng có thể đăng lệch vài phút.

## F. API cần cấp quyền

- Facebook Page: Page ID + Page Access Token có quyền đăng video, `pages_manage_posts`, `pages_read_engagement` và Page task `CREATE_CONTENT`, cùng quyền ứng dụng phù hợp. Khi bật FULL_PLATFORMS có `facebook`, phải thử API `/page_id/videos` thực tế.
- YouTube: OAuth Desktop với scope `https://www.googleapis.com/auth/youtube.upload`; không cần tạo API mới để đăng video dài.

## Giới hạn V3

- Chưa tự cắt highlight / chọn đoạn viral bằng AI.
- Chưa có Meta resumable uploads cho file dài trên 1 GB.
- Chưa có cách đảm bảo một video được nền tảng gắn nhãn 'video thường' thay vì 'Reels'.
- Chưa có cross-platform publication time offset hay dashboard web.
- Không có token thật trong ZIP, chưa test đăng thật với Fanpage/kênh YouTube của người dùng.
- **Repo GitHub Pages `hoang-auto-publisher` chỉ là website OAuth**, không nên thay các file `index.html`, `privacy.html`, `terms.html`, `styles.css` bằng source Python này.