# Việc làm Data

Website tổng hợp việc làm ngành data tại Việt Nam. Lương được quy đổi hết sang triệu VNĐ/tháng (ngoại tệ theo tỷ giá hiện tại, có dấu ≈). Chạy hoàn toàn miễn phí trên GitHub:

- **GitHub Actions** chạy `scrape.py` 6 tiếng/lần → cập nhật `jobs.json`
- **Máy của bạn** chạy `local.py` 6 tiếng/lần (Task Scheduler) → cập nhật `local.json`, cho các trang chặn hoặc có thể chặn máy chủ GitHub
- **GitHub Pages** hiển thị `index.html` tại `https://<tên-tổ-chức>.github.io`

| File | Việc |
|---|---|
| `scrape.py` | Lấy job từ VietnamWorks, CareerViet, LinkedIn Jobs, Ybox, TopDev, Glints và trang tuyển dụng của các công ty: 19 ngân hàng (Vietcombank, VietinBank, Techcombank, VPBank, ACB, VIB…), chứng khoán (SSI, VNDIRECT, TCBS), VNPAY, VNG, MoMo, VNPT, NashTech, Grab, NVIDIA, NAB, Prudential… |
| `local.py` | Lấy job từ ITviec, TopCV, CareerLink, JobsGo, Vieclam24h (các trang chặn máy chủ GitHub) |
| `index.html` | Trang web: lưới thẻ việc làm, rê chuột (hoặc chạm trên điện thoại) để xem nhanh, tìm kiếm (gõ không dấu cũng được), lọc theo mức lương, tỉnh thành, thời điểm đăng, kinh nghiệm, nguồn |

## Đưa website lên mạng (khoảng 10 phút)

Link sẽ có dạng `https://vieclamdata.github.io`: dùng một Organization (miễn phí) đặt tên theo website thay vì tên tài khoản cá nhân.

1. Đăng nhập https://github.com, bấm **+ → New organization → Free**, đặt tên ví dụ `vieclamdata` (tên phải còn trống).
2. Trong organization vừa tạo, bấm **New repository**, đặt tên **đúng** `vieclamdata.github.io` (tên tổ chức + `.github.io`), chọn **Public**, không tick README, .gitignore hay license.
3. Vào **Settings của organization → Actions → General → Workflow permissions**, chọn **Read and write permissions**, Save.
4. Lần đầu dùng git trên máy, khai báo tên và email cho commit. Repo Public thì ai cũng xem được email này, nên dùng email ẩn danh: **Settings (tài khoản) → Emails**, tick **Keep my email addresses private**, copy địa chỉ dạng `12345678+username@users.noreply.github.com`.
   ```powershell
   git config --global user.name "Tên của bạn"
   git config --global user.email "12345678+username@users.noreply.github.com"
   ```
5. Đưa code lên (thay `vieclamdata` bằng tên tổ chức của bạn). Lần đầu push, Windows mở cửa sổ đăng nhập GitHub:
   ```powershell
   cd C:\Users\nguye\Documents\data_job_website
   git add .
   git commit -m "init"
   git remote add origin https://github.com/vieclamdata/vieclamdata.github.io.git
   git push -u origin main
   ```
6. Trong repo: **Settings → Actions → General → Workflow permissions** → **Read and write permissions**, Save. Rồi **Settings → Pages → Deploy from a branch** → `main` / `(root)`, Save.
7. Tab **Actions → scrape → Run workflow** để chạy lần đầu (GitHub hỏi bật workflow thì đồng ý). Chờ 3–5 phút, rồi mở **https://vieclamdata.github.io**

Từ đây trang tự cập nhật 6 tiếng/lần. Nếu một nguồn bị hỏng (trang đổi giao diện hoặc chặn), workflow báo đỏ và GitHub gửi email cho bạn. Log sẽ ghi dòng `Nguồn cần kiểm tra: <tên>`, bạn chỉ cần sửa hàm cùng tên trong `scrape.py`. Các nguồn khác vẫn cập nhật bình thường. Máy chủ của GitHub đặt ở nước ngoài, nên có trang Việt Nam có thể chặn ngay từ lần chạy đầu dù trên máy bạn vẫn chạy được.

**Sửa code sau này:** bot commit `jobs.json` mỗi 6 tiếng, nên luôn lấy bản mới về trước khi sửa và trước khi push:
```powershell
git pull
# ...sửa code...
git add .
git commit -m "mô tả thay đổi"
git pull --rebase
git push
```
Đừng commit `jobs.json` sinh ra từ máy bạn, vì sẽ đụng với bản bot vừa cập nhật. Nếu đã lỡ chạy `python scrape.py` trên máy, chạy `git checkout jobs.json` để bỏ thay đổi đó trước khi commit.

Muốn tên miền riêng (`vieclamdata.com`, khoảng 250 nghìn đồng/năm): mua tên miền, thêm 4 bản ghi A trỏ tới `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153` và CNAME `www` → `vieclamdata.github.io`, rồi nhập tên miền ở **Settings → Pages → Custom domain**.

## Cào bằng máy của bạn (`local.py`)

Đã thử trên máy chủ GitHub (10/2026): ITviec, TopCV, JobsGo, Vieclam24h trả lỗi 403, CareerLink trả trang rỗng. Các trang này do `local.py` lấy bằng IP Việt Nam, ghi vào `local.json` rồi tự push. Bot GitHub chỉ ghi `jobs.json`, nên hai bên không bao giờ xung đột. Không cần trình duyệt: mọi request đi qua [Scrapling](https://github.com/D4Vinci/Scrapling), giả lập Chrome tới cả dấu vân tay TLS nên Cloudflare của TopCV, JobsGo không chặn.

1. Cài một lần: `pip install -r requirements.txt`
2. Chạy thử không push: `python local.py --no-push`
3. Lịch tự chạy 6 tiếng/lần đã được tạo bằng lệnh dưới (tên `vieclamdata-local`). Máy phải bật và đã đăng nhập Windows.
   ```powershell
   schtasks /Create /TN vieclamdata-local /SC HOURLY /MO 6 /ST 07:00 /F /TR "cmd /c cd /d C:\Users\nguye\Documents\data_job_website && python local.py >> local.log 2>&1"
   ```
   - Chạy ngay: `schtasks /Run /TN vieclamdata-local`
   - Xem kết quả: mở `local.log` (dòng `Nguồn cần kiểm tra: ...` nếu có trang hỏng)
   - Tắt lịch: `schtasks /Delete /TN vieclamdata-local /F`

## Chạy thử trên máy

```powershell
pip install -r requirements.txt
python scrape.py
python -m http.server
```
Mở http://localhost:8000

## Thêm một trang tuyển dụng mới

Trong `scrape.py`, viết một hàm trả về danh sách `job(title, company, location, region, url, source, date)` rồi thêm tên hàm vào `SOURCES`. Nếu nguồn có thì truyền thêm `logo=`, `salary=`, `tags=`, `desc=` (mô tả đầy đủ, HTML cũng được) cho khung xem nhanh. Từ khóa lọc ngành data nằm ở `DATA_RE`, `NOT_DATA_RE` và `OTHER_ROLE_RE`.

**Kỹ năng trên thẻ việc làm** được đọc từ mô tả tin theo danh sách `SKILLS` trong `scrape.py` (thêm kỹ năng = thêm một dòng tên + từ khóa). Tin nào danh sách không kèm mô tả thì `run()` đọc trang chi tiết của tin, mỗi tin một lần.

**Chương trình Management Trainee / Graduate / Future Leader / Quản trị viên tập sự**: tên thường không ghi "data", nên được giữ khi mô tả tin đòi kỹ năng data (SQL, Python, Power BI…, xem `TRAINEE_RE` và `DATA_SKILLS`).

## Thêm trang tuyển dụng của một công ty

Nhiều công ty đăng tin qua hệ thống tuyển dụng có API công khai. Mở trang tuyển dụng của công ty, bấm vào một tin rồi xem link:

| Link có dạng | Thêm vào `COMPANIES` trong `scrape.py` |
|---|---|
| `job-boards.greenhouse.io/abc/...` | `(greenhouse, "abc", "Tên công ty"),` |
| `jobs.lever.co/abc/...` | `(lever, "abc", "Tên công ty"),` |
| `jobs.ashbyhq.com/abc/...` | `(ashby, "abc", "Tên công ty"),` |
| `jobs.smartrecruiters.com/abc/...` | `(smartrecruiters, "abc", "Tên công ty"),` |
| `abc.wd3.myworkdayjobs.com/en-US/Trang_ABC/...` (Workday, như NVIDIA, NAB, Prudential) | `(workday, "abc.wd3/Trang_ABC", "Tên công ty"),` |
| Trang có ảnh từ `centralize-api.ainavi.com.vn`, link tin dạng `/vi/jobs/<mã>` (Ainavi, như TPBank, OCB, LPBank) | `(ainavi, "tuyendung.abc.com.vn", "Tên công ty"),` |
| Mã nguồn trang có `Client.pageData=` (Base E-hiring, như VIB, ACB, ABBank) | `(base, "<địa chỉ trang tất cả việc làm>", "Tên công ty"),` |
| Trang có `<địa chỉ>/services/rss/job/` (SAP SuccessFactors, như VPBank) | `(successfactors, "https://tuyendung.abc.com.vn", "Tên công ty"),` |
| Trang có ảnh từ `image.talentnetwork.vn`, link tin dạng `/viec-lam/ten-vi-tri.35ac13c7.html` (như SHB, PVcomBank) | `(talentnetwork, "https://tuyendung.abc.com.vn", "Tên công ty"),` |

Chỉ tin ở Việt Nam và đúng ngành data mới được lấy. Công ty tự làm trang tuyển dụng riêng thì mỗi trang một hàm (`vng`, `momo`, `be`, `vnpt`, `nashtech`, `vietinbank`, `seabank`, `msb`, `ssi`, `tcbs`, `vnpay` trong `scrape.py`), nằm trong `SOURCES` như các trang tuyển dụng. Trang nào đổi giao diện thì workflow báo đỏ với tên hàm đó. Đã thử nhưng chưa làm được: FPT, Tiki, Ahamove, BIDV, Kienlongbank, vì các trang này tải danh sách bằng JavaScript hoặc chặn API; VinBigData không còn cập nhật từ 2022.

**Logo:** trang tuyển dụng của công ty không kèm logo, nên logo lấy từ thư mục `logos/`, tên file là tên công ty viết không dấu, nối bằng gạch ngang (`Nam A Bank` → `logos/nam-a-bank.png`; `logos/vnpt.png` dùng cho mọi đơn vị có chữ VNPT). Thêm công ty mới thì thêm một file PNG vuông khoảng 160px, nền trong suốt hoặc trắng. Không có file thì dùng logo của tin khác cùng tên công ty (từ ITviec, TopCV...), vẫn không có thì trang hiện chữ cái đầu.

Cấp bậc kinh nghiệm được đoán từ tên vị trí ("Senior", "Trưởng phòng", "Intern"...). Nếu tên không ghi thì dùng nhãn cấp bậc của nguồn. Từ khóa nằm ở `LEVELS` trong `scrape.py`.

## Chưa hỗ trợ

- **Indeed**: Cloudflare chặn cả trình duyệt thật.
- **FPT, Tiki**: trang tuyển dụng không hiện danh sách tin công khai.
- **123job, Joboko, Timviec365**: chủ yếu đăng lại tin từ trang khác → trùng lặp, nên không lấy.
