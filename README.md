# Việc làm Data

Website tổng hợp việc làm ngành data tại Việt Nam. Lương được quy đổi hết sang triệu VNĐ/tháng (ngoại tệ theo tỷ giá hiện tại, có dấu ≈). Chạy hoàn toàn miễn phí trên GitHub:

| File | Việc |
|---|---|
| `scrape.py` | Lấy job từ VietnamWorks, CareerViet, LinkedIn Jobs, Ybox, TopDev, Glints và trang tuyển dụng của các công ty: 19 ngân hàng (Vietcombank, VietinBank, Techcombank, VPBank, ACB, VIB…), chứng khoán (SSI, VNDIRECT, TCBS), VNPAY, VNG, MoMo, VNPT, NashTech, Grab, NVIDIA, NAB, Prudential… |
| `local.py` | Lấy job từ ITviec, TopCV, CareerLink, JobsGo, Vieclam24h và trang tuyển dụng VietinBank (các trang chặn máy chủ GitHub) |
| `index.html` | Trang web: lưới thẻ việc làm, rê chuột (hoặc chạm trên điện thoại) để xem nhanh, tìm kiếm (gõ không dấu cũng được), lọc theo mức lương, tỉnh thành, thời điểm đăng, kinh nghiệm, nguồn |

## Đưa website lên mạng (khoảng 10 phút)

Link sẽ có dạng `https://vieclamdata.github.io`

Trang tự cập nhật 6 tiếng/lần. Nếu một nguồn bị hỏng (trang đổi giao diện hoặc chặn), workflow báo đỏ. Log sẽ ghi dòng `Nguồn cần kiểm tra: <tên>`. Các nguồn khác vẫn cập nhật bình thường. 

**Kỹ năng trên thẻ việc làm** được đọc từ mô tả tin theo danh sách `SKILLS` trong `scrape.py` (thêm kỹ năng = thêm một dòng tên + từ khóa). Tin nào danh sách không kèm mô tả thì `run()` đọc trang chi tiết của tin, mỗi tin một lần.

**Chương trình Management Trainee / Graduate / Future Leader / Quản trị viên tập sự**: tên thường không ghi "data", nên được giữ khi mô tả tin đòi kỹ năng data (SQL, Python, Power BI…, xem `TRAINEE_RE` và `DATA_SKILLS`).

Chỉ tin ở Việt Nam và đúng ngành data mới được lấy. Công ty tự làm trang tuyển dụng riêng thì mỗi trang một hàm (`vng`, `momo`, `be`, `vnpt`, `nashtech`, `seabank`, `msb`, `ssi`, `tcbs`, `vnpay` trong `scrape.py`), nằm trong `SOURCES` như các trang tuyển dụng. Trang nào đổi giao diện thì workflow báo đỏ với tên hàm đó. Đã thử nhưng chưa làm được: FPT, Tiki, Ahamove, BIDV, Kienlongbank, vì các trang này tải danh sách bằng JavaScript hoặc chặn API; VinBigData không còn cập nhật từ 2022.

**Logo:** trang tuyển dụng của công ty không kèm logo, nên logo lấy từ thư mục `logos/`, tên file là tên công ty viết không dấu, nối bằng gạch ngang (`Nam A Bank` → `logos/nam-a-bank.png`; `logos/vnpt.png` dùng cho mọi đơn vị có chữ VNPT). Thêm công ty mới thì thêm một file PNG vuông khoảng 160px, nền trong suốt hoặc trắng. Không có file thì dùng logo của tin khác cùng tên công ty (từ ITviec, TopCV...), vẫn không có thì trang hiện chữ cái đầu.

Cấp bậc kinh nghiệm được đoán từ tên vị trí ("Senior", "Trưởng phòng", "Intern"...). Nếu tên không ghi thì dùng nhãn cấp bậc của nguồn. Từ khóa nằm ở `LEVELS` trong `scrape.py`.

## Chưa hỗ trợ

- **Indeed**: Cloudflare chặn cả trình duyệt thật.
- **FPT, Tiki**: trang tuyển dụng không hiện danh sách tin công khai.
- **123job, Joboko, Timviec365**: chủ yếu đăng lại tin từ trang khác → trùng lặp, nên không lấy.
