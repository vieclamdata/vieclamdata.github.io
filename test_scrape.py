"""Kiểm tra bộ lọc và cách đọc thông tin hiển thị trên web. Chạy: python test_scrape.py (không cần mạng)."""
from scrape import exp_label, experience, is_data_job, job, levels, lines, months, sections, skills

# nghề quant: giữ
for t in ["Quant Researcher", "Chuyên viên Phân tích định lượng (Quant)", "Nhà Nghiên Cứu Định Lượng", "Appointed Actuary",
          "Nhân Viên Định Phí", "Senior Manager, Actuarial Pricing (Compensation Projects)", "Cán bộ tính toán bảo hiểm - Actuary",
          "Chuyên viên xây dựng mô hình rủi ro tín dụng", "Model Validation Specialist", "AI Quantitative Researcher Intern"]:
    assert is_data_job(t), t
# "định lượng" của bếp, kho; mô hình kinh doanh; quantity: loại
for t in ["Nhân Viên Định Lượng (Nhận Sinh Viên Mới Ra Trường)", "Trưởng Bộ Phận Thực Đơn & Định Lượng", "Quantity Surveyor",
          "Chuyên viên phát triển mô hình kinh doanh", "Covered Warrant Trader"]:
    assert not is_data_job(t), t

# số năm kinh nghiệm: câu thật trong kho
cases = {
    "Mandatory Requirements From 3–4 years of experience. Proven": (3, 4),
    "Tối thiểu 1 - 2 năm kinh nghiệm trong lĩnh vực Data Science": (1, 2),
    "Dưới 1 năm kinh nghiệm chuyên môn": (0, 1),
    "Có kinh nghiệm làm việc ở vị trí tương đương tối thiểu 01 năm.": (1, None),
    "Kinh nghiệm: 2 Năm Cấp bậc: Nhân viên": (2, None),
    "5+ years experience as a data engineer": (5, None),
    "Experience - 3–5 years in data governance": (3, 5),
    "Have at least 5 years and above practical experience in managing": (5, None),
    "7+ years’ experience in marketing": (7, None),
    "Fresh graduates are welcome; up to 1 year of experience in Data Analysis": (0, 1),
    "Kinh nghiệm: Từ 3 năm Tốt nghiệp Đại học": (3, None),
    "Có từ 3 năm kinh nghiệm làm việc ở vị trí Data Engineer. ( 1 năm kinh nghiệm quản lý )": (3, None),  # yêu cầu chính nhắc trước
    "Quantitative Researcher - Không Yêu Cầu Kinh Nghiệm - Thu Nhập Hấp Dẫn": (0, None),
    "At least 3-year experience in manufacturing": (3, None),
    "Experiences3 Years SalaryNegotiable": (3, None),
    "Key Qualifications & Experience 3-4yearsofexperience in data analytics": (3, 4),
    "2+ years of hands-on BI/Data Analyst experience with end-to-end delivery": (2, None),
    "Chưa có kinh nghiệm được đào tạo bài bản": (0, None),
    # mỗi cấp một mức → khoảng thấp nhất–cao nhất
    "3 năm (Chuyên viên cao cấp)/ 2 năm (Chuyên viên chính)/ 1 năm (Chuyên viên) kinh nghiệm ở vị trí tuyển dụng": (1, 3),
    "Từ 2 năm (Middle) đến 4+ năm (Senior) kinh nghiệm NLP/ML Engineering": (2, 4),
    "At least 3 years (Senior Officer)/2 years (Officer) of working experience in the field": (2, 3),
    "with our 30+ years of engineering execution to speed our clients": None,  # tuổi công ty
    "NLĐ được tuyển dụng vào học việc tại ngân hàng mà chưa có kinh nghiệm, Thực hiện chuyên môn": None,
    "Thưởng các ngày lễ. Được xem xét tăng lương 02 lần/01 năm": None,
}
for text, want in cases.items():
    assert experience(text) == want, (text, experience(text))
assert [exp_label(2, 3), exp_label(5, None), exp_label(0, None), exp_label(0, 1), exp_label(2, 2)] == \
       ["2–3 năm", "5+ năm", "Không yêu cầu", "0–1 năm", "2+ năm"]

# cấp bậc: viết tắt ngân hàng, bậc II/III, suy từ số năm khi tên không ghi
assert levels("CV/CVCC Phân tích dữ liệu") == ["senior"]
assert levels("Chuyên viên chính Quản trị dữ liệu") == ["mid"]
assert levels("Data Engineer II") == ["mid"] and levels("Data Engineer III") == ["senior"]
assert levels("Data Analyst", years=0) == ["intern"] and levels("Data Analyst", years=3) == ["mid"] and levels("Data Analyst") == []

# kỹ năng quant
assert {"C++", "Kinh tế lượng", "Chuỗi thời gian", "Mô hình rủi ro", "Stochastic / Monte Carlo"} <= set(
    skills("C++, econometrics, time-series forecasting, credit scoring, Monte Carlo simulation"))
assert "Stata / EViews" not in skills("customer reviews")

# job(): số năm và lương ghi trong tên tin
desc = "Yêu cầu: Tối thiểu 2 - 3 năm kinh nghiệm phân tích dữ liệu, thành thạo SQL, Python. " * 10
j = job("Data Analyst", "X", "Hà Nội", "VN", "u", "s", "2026-11-09", desc=desc)
assert j["exp"] == "2–3 năm" and j["level"] == ["mid"] and j["skills"][:2] == ["SQL", "Python"], j
assert job("Senior Data Analyst", "X", "", "VN", "u", "s", "d", exp=(0, 1))["level"] == ["senior"]  # tên ghi cấp bậc thì theo tên
assert job("Lead Data Analyst ( Thu nhập 45-55M)", "X", "", "VN", "u", "s", "d")["salary"] == "45–55 triệu"
assert job("Lead Data Analyst - Lương Up To 40M + Thưởng", "X", "", "VN", "u", "s", "d")["salary"] == "Đến 40 triệu"
assert "salary" not in job("Data Analyst - Thu Nhập Hấp Dẫn, Lương Tháng 13", "X", "", "VN", "u", "s", "d")

# số năm trong JobPosting (CareerViet, ITviec)
assert months({"monthsOfExperience": 36}) == (3, None) and months({"monthsOfExperience": 10}) == (0, 1) and months({}) is None

# khung xem nhanh chia mục: tiêu đề có số thứ tự/viết hoa/":", phần đầu không tiêu đề, tiêu đề phụ, mục bỏ đi
html_desc = """<ul><li>Xây dựng dashboard Tableau</li><li>Viết SQL</li></ul>
<p>Yêu cầu công việc</p><ul><li>Có từ 03 năm kinh nghiệm</li><li>Kỹ năng giao tiếp tốt</li></ul>
<p><strong>3. QUYỀN LỢI:</strong></p><p>• Lương tháng 13 • Bảo hiểm sức khỏe</p>
<p>Cách thức ứng tuyển:</p><p>Gửi CV về email</p>"""
assert sections(lines(html_desc)) == [["Mô tả công việc", ["Xây dựng dashboard Tableau", "Viết SQL"]],
                                      ["Yêu cầu", ["Có từ 03 năm kinh nghiệm", "Kỹ năng giao tiếp tốt"]],
                                      ["Quyền lợi", ["Lương tháng 13", "Bảo hiểm sức khỏe"]]], sections(lines(html_desc))
li = "About us\nWe are a bank.\nResponsibilities\nBuild pipelines\nKinh nghiệm: 2 năm\nWhat you will bring\nPython\nTop 3 Reasons To Join Us\nRemote"
assert sections(lines(li)) == [["Mô tả công việc", ["Build pipelines", "Kinh nghiệm: 2 năm"]], ["Yêu cầu", ["Python"]], ["Quyền lợi", ["Remote"]]], sections(lines(li))
assert sections(lines("Intro dòng 1\nJob Description\nDo X")) == [["Giới thiệu", ["Intro dòng 1"]], ["Mô tả công việc", ["Do X"]]]
# ngắt dòng cứng giữa câu (MoMo) → nối; tiêu đề phụ bỏ; mục xếp theo thứ tự cố định
assert lines("Turn people and\nbusiness data into insights.\nBuild KPIs") == ["Turn people and business data into insights.", "Build KPIs"]
assert lines("<li>Một</li><li>hai</li>") == ["Một", "hai"]  # ranh giới thẻ thì không nối
assert lines("Vận hành<br>giám sát pipeline dữ liệu hằng ngày cho toàn bộ các hệ thống nghiệp vụ của ngân hàng, kể cả hệ thống lõi; "
             "chủ động phát hiện, phân tích nguyên nhân và xử lý sự cố phát sinh trong quá trình vận hành hằng ngày. Kiểm tra dữ liệu.") == \
       ["Vận hành giám sát pipeline dữ liệu hằng ngày cho toàn bộ các hệ thống nghiệp vụ của ngân hàng, kể cả hệ thống lõi; "
        "chủ động phát hiện, phân tích nguyên nhân và xử lý sự cố phát sinh trong quá trình vận hành hằng ngày.", "Kiểm tra dữ liệu."]
assert sections(lines("Top 3 Reasons To Join Us\nBonus\nResponsibilities\nKey Responsibilities\nDo X")) == \
       [["Mô tả công việc", ["Do X"]], ["Quyền lợi", ["Bonus"]]]
# đoạn dài một dòng → tách theo câu / số thứ tự
long = "1. Vận hành nền tảng dữ liệu, đảm bảo chất lượng và độ ổn định cho toàn hệ thống. 2. Phối hợp với các khối nghiệp vụ để xây dựng báo cáo. Mức lương cứng từ 12 - 16 triệu. - Thưởng quý, thưởng năm theo kết quả."
assert lines(long) == ["1. Vận hành nền tảng dữ liệu, đảm bảo chất lượng và độ ổn định cho toàn hệ thống.",
                       "2. Phối hợp với các khối nghiệp vụ để xây dựng báo cáo.", "Mức lương cứng từ 12 - 16 triệu.",
                       "Thưởng quý, thưởng năm theo kết quả."], lines(long)
print("OK")
