# Việc làm Data

Website tổng hợp việc làm ngành data tại Việt Nam. Lương được quy đổi hết sang triệu VNĐ/tháng (ngoại tệ theo tỷ giá hiện tại, có dấu ≈). Chạy hoàn toàn miễn phí trên GitHub:

| File | Việc |
|---|---|
| `scrape.py` | Lấy job từ VietnamWorks, CareerViet, LinkedIn Jobs, Ybox, TopDev, Glints và trang tuyển dụng của các công ty: 19 ngân hàng (Vietcombank, VietinBank, Techcombank, VPBank, ACB, VIB…), chứng khoán (SSI, VNDIRECT, TCBS), VNPAY, VNG, MoMo, VNPT, NashTech, Grab, NVIDIA, NAB, Prudential… |
| `local.py` | Lấy job từ ITviec, TopCV, CareerLink, JobsGo, Vieclam24h và trang tuyển dụng VietinBank (các trang chặn máy chủ GitHub) |
| `index.html` | Trang web: lưới thẻ việc làm, rê chuột (hoặc chạm trên điện thoại) để xem nhanh, tìm kiếm (gõ không dấu cũng được), lọc theo mức lương, tỉnh thành, thời điểm đăng, kinh nghiệm, nguồn |
| `archive/` | Kho lưu trữ mọi job từng thấy, kể cả đã quá 30 ngày (trang web chỉ hiện 30 ngày gần nhất) |
| `archive.py` | Gộp kho thành cơ sở dữ liệu SQLite `archive.db` để truy vấn |

## Website

Link sẽ có dạng `https://vieclamdata.github.io`

Trang tự cập nhật 6 tiếng/lần. Nếu một nguồn bị hỏng (trang đổi giao diện hoặc chặn), workflow báo đỏ. Log sẽ ghi dòng `Nguồn cần kiểm tra: <tên>`. Các nguồn khác vẫn cập nhật bình thường. 

**Kỹ năng trên thẻ việc làm** được đọc từ mô tả tin theo danh sách `SKILLS` trong `scrape.py` (thêm kỹ năng = thêm một dòng tên + từ khóa). Tin nào danh sách không kèm mô tả thì `run()` đọc trang chi tiết của tin, mỗi tin một lần.

**Chương trình Management Trainee / Graduate / Future Leader / Quản trị viên tập sự**: tên thường không ghi "data", nên được giữ khi mô tả tin đòi kỹ năng data (SQL, Python, Power BI…, xem `TRAINEE_RE` và `DATA_SKILLS`).

Chỉ tin ở Việt Nam và đúng ngành data mới được lấy. Công ty tự làm trang tuyển dụng riêng thì mỗi trang một hàm (`vng`, `momo`, `be`, `vnpt`, `nashtech`, `seabank`, `msb`, `ssi`, `tcbs`, `vnpay` trong `scrape.py`), nằm trong `SOURCES` như các trang tuyển dụng. Trang nào đổi giao diện thì workflow báo đỏ với tên hàm đó. Đã thử nhưng chưa làm được: FPT, Tiki, Ahamove, BIDV, Kienlongbank, vì các trang này tải danh sách bằng JavaScript hoặc chặn API; VinBigData không còn cập nhật từ 2022.

**Logo:** trang tuyển dụng của công ty không kèm logo, nên logo lấy từ thư mục `logos/`, tên file là tên công ty viết không dấu, nối bằng gạch ngang (`Nam A Bank` → `logos/nam-a-bank.png`; `logos/vnpt.png` dùng cho mọi đơn vị có chữ VNPT). Thêm công ty mới thì thêm một file PNG vuông khoảng 160px, nền trong suốt hoặc trắng. Không có file thì dùng logo của tin khác cùng tên công ty (từ ITviec, TopCV...), vẫn không có thì trang hiện chữ cái đầu.

Cấp bậc kinh nghiệm được đoán từ tên vị trí ("Senior", "Trưởng phòng", "Intern"...). Nếu tên không ghi thì dùng nhãn cấp bậc của nguồn. Từ khóa nằm ở `LEVELS` trong `scrape.py`.

## Kho lưu trữ (cơ sở dữ liệu)

`jobs.json` / `local.json` chỉ giữ job 30 ngày gần nhất cho trang web. Mỗi lần chạy, mọi job còn được ghi vào kho `archive/<nguồn>-<tháng thấy lần đầu>.jsonl` (mỗi dòng một job). Bot ghi `archive/jobs-*`, `local.py` ghi `archive/local-*`, nên hai bên không xung đột.

Kho là file chữ để git chỉ lưu phần thay đổi. Sau mỗi lần chạy, bot tạo cơ sở dữ liệu SQLite `archive.db` từ toàn bộ kho và đăng lên Release `db` của repo (ghi đè bản cũ, không nằm trong lịch sử git nên repo không phình). Tải bản mới nhất, mở bằng DB Browser for SQLite, DBeaver, Python...:

**https://github.com/vieclamdata/vieclamdata.github.io/releases/download/db/archive.db**

Muốn tạo ngay trên máy (ví dụ vừa chạy `local.py`): `git pull` rồi `python archive.py`.

Kho lưu **toàn bộ thông tin** của tin, còn `jobs.json` chỉ giữ phần trang web cần: `full` = mô tả đầy đủ (mô tả, yêu cầu, quyền lợi; tin không kèm mô tả thì đọc từ trang chi tiết, mỗi tin một lần), `salary_raw` = lương ghi nguyên văn, `raw` = bản ghi gốc của nguồn (JSON từ API, hoặc chữ trên thẻ tin với trang HTML: hạn nộp, loại hình, số lượng...). Các trường này nằm ở `ARCHIVE_ONLY` trong `scrape.py`.

Kho được dựng lại từ lịch sử git từ tháng 9/2026; job bị xóa trước đó và không còn trong lịch sử thì không lấy lại được. Tin cào trước 16/10/2026 chưa có `full`, `raw`: tin còn đăng sẽ được bổ sung ở các lần chạy sau, tin đã gỡ thì chỉ có phần đã lưu trong `jobs.json` cũ.

## Chưa hỗ trợ

- **Indeed**: Cloudflare chặn cả trình duyệt thật.
- **FPT, Tiki**: trang tuyển dụng không hiện danh sách tin công khai.
- **123job, Joboko, Timviec365**: chủ yếu đăng lại tin từ trang khác → trùng lặp, nên không lấy.
