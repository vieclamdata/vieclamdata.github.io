"""Thu thập việc làm ngành data từ các trang tuyển dụng → jobs.json.

Chạy: python scrape.py   (GitHub Actions tự chạy 6 tiếng/lần)
"""
import html
import json
import logging
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from bs4 import BeautifulSoup
from scrapling.fetchers import Fetcher

logging.getLogger("scrapling").setLevel(logging.WARNING)  # bỏ dòng log mỗi request
TODAY = date.today().isoformat()
KEEP_DAYS = 30

# nghề định lượng (quant, actuary, mô hình rủi ro). "định lượng" đứng một mình còn là việc bếp, kho ("Nhân viên định lượng")
# → chỉ nhận khi đi với nghiệp vụ tài chính; "mô hình kinh doanh" là business model, không phải mô hình định lượng.
QUANT = (r"\bquant(?:itative)?\b|(?:phân tích|nghiên cứu|mô hình|giao dịch|đầu tư|tài chính|rủi ro) định lượng|actuar|định phí|tính toán bảo hiểm"
         r"|algo(?:rithmic)? trad|giao dịch thuật toán|econometric|kinh tế lượng|statistician|biostatistic"
         r"|(?:risk|credit|pricing|scoring) model|model (?:validation|risk|development)|credit scor|scorecard"
         r"|(?:xây dựng|phát triển|kiểm định) mô hình(?! kinh doanh)|mô hình (?:rủi ro|định lượng|tín dụng|chấm điểm|xếp hạng)")
# (?-i:...) = phân biệt hoa thường, để "BI"/"ML" không khớp "mobile", "html"...
DATA_RE = re.compile(
    r"\bdata\b|dữ liệu|business intelligence|analytics|machine learning|deep learning|power ?bi|tableau|"
    r"(?-i:\bBI\b|\bML\b|\bMLOps\b|\bETL\b|\bSQL\b)|(?-i:\bAI\b) (?:engineer|scientist)|" + QUANT,
    re.I,
)
# luôn loại: "data" mang nghĩa khác (danh sách khách hàng của sales, trung tâm dữ liệu, tính từ), nhập/gán nhãn dữ liệu, DBA
NOT_DATA_RE = re.compile(
    r"data entry|nhập (?:dữ )?liệu|data (?:\w+ ){0,2}(?:có )?sẵn|data nóng|spam data|data cent(?:er|re)|hạ tầng trung tâm dữ liệu|data[- ]driven|annotat|gán nhãn"
    # sales VN: "data" = danh sách khách hàng được giao ("Hỗ trợ Data", "Sẵn 100% Data", "Data công ty cấp", "Nhắc phí theo Data")
    r"|(?:hỗ trợ|có sẵn|sẵn|có|cung cấp|theo|gọi|tìm) (?:100% )?data\b|data (?:được |công ty )*(?:cung )?cấp|data topup"
    r"|telesales|telemarketing|quản trị cơ sở dữ liệu|\bDBA\b|database administrat|sql server administrat",
    re.I,
)
# vị trí thuộc nghề khác (sales, HR, pháp chế, hành chính, hỗ trợ) chỉ nhắc tới data/analytics → loại,
# trừ khi tên vị trí là vai trò data rõ ràng ("Sales Data Analyst", "HR Data Analyst" vẫn giữ)
OTHER_ROLE_RE = re.compile(
    r"\bsales\b|account (?:executive|manager)|business development|nhân viên kinh doanh|chuyên viên kinh doanh|bán hàng"
    r"|recruit|talent acquisition|tuyển sinh|nhân sự|nguồn nhân lực|\bHR\b|counsel|pháp chế|compensation|hành chính"
    r"|customer (?:service|support|success)|chăm sóc khách hàng|application support"
    r"|tư vấn|nhắc phí|cskh|qua điện thoại|gọi điện|bất động sản|\bbđs\b|phát triển thị trường|kho hàng"
    r"|(?:nhóm|giám đốc|trưởng phòng) kinh doanh",
    re.I,
)
DATA_ROLE_RE = re.compile(
    r"data (?:analyst|engineer|scientist|architect|science|analytics|modeler|consultant)|phân tích dữ liệu|kỹ sư dữ liệu|khoa học dữ liệu"
    r"|machine learning|business intelligence|power ?bi|tableau|" + QUANT,  # "Actuarial Pricing (Compensation...)" vẫn giữ
    re.I,
)

# cấp bậc → từ khóa trong tên vị trí hoặc nhãn cấp bậc của nguồn. "Junior/Fresher" khớp cả hai.
LEVELS = {
    "intern": r"\bintern(?:ship)?\b|thực tập|fresher|trainee|\bgraduate\b|mới tốt nghiệp|sinh viên|entry[- ]level"
              r"|tập sự|future leader|young (?:talent|leader)|fast[- ]track|tài năng trẻ",
    "junior": r"\bjunior\b|\bjr\b|(?<!senior )\bassociate\b(?!\s+director)",  # "Associate" = nhãn junior của LinkedIn/SmartRecruiters
    # ngân hàng: CV (chuyên viên) → CVC (chuyên viên chính, ~2 năm) → CVCC (cao cấp, ~4 năm) → chuyên gia; "Data Engineer II/III"
    "mid": r"\bmid(?:dle)?\b(?!\s*east)|intermediate|midweight|\bcvc\b|chuyên viên chính|(?-i:\bII\b)",
    "senior": r"\bsenior\b|\bsr\b|cao cấp|\bcvcc\b|\bexpert\b|chuyên gia|(?-i:\bIII\b)",
    # "staff" chỉ tính khi là cấp kỹ sư ("Staff Data Engineer"); ở VN "BI Staff" = nhân viên.
    # "tăng trưởng" (growth) không phải "trưởng phòng"; "quản lý" chỉ tính ở đầu tên, "chuyên viên quản lý dữ liệu" là nghiệp vụ.
    "lead": r"(?<!future )(?<!young )\blead(?:er)?\b|\bhead\b|manager|director|principal|\bchief\b|\bvp\b|supervisor|staff (?:\w+ ){0,3}(?:engineer|scientist|architect)"
            r"|(?<!tăng )trưởng|phó phòng|giám đốc|^quản lý",
}

# kỹ năng → từ khóa trong tên + mô tả tin. Tên hiển thị trên thẻ việc làm, xếp theo thứ tự xuất hiện trong tin.
SKILLS = {
    "SQL": r"\bsql\b|postgre|mysql|oracle db|t-sql|pl/sql", "Python": r"\bpython\b", "R": r"(?-i:\bR\b)(?![&'’-])|\br programming|\brstudio\b",
    "Excel": r"\bexcel\b", "VBA": r"(?-i:\bVBA\b)", "Power BI": r"power ?bi\b", "Tableau": r"tableau", "Looker": r"looker|data studio",
    "Qlik": r"\bqlik", "Alteryx": r"alteryx", "Superset": r"superset", "Metabase": r"metabase", "Google Analytics": r"google analytics|\bGA4\b",
    "Thống kê": r"statistic|thống kê|xác suất", "Machine Learning": r"machine learning|(?<!khoa )học máy|(?-i:\bML\b)", "Deep Learning": r"deep learning|học sâu",
    "NLP": r"\bnlp\b|natural language|ngôn ngữ tự nhiên", "Computer Vision": r"computer vision|thị giác máy tính",
    "LLM / GenAI": r"\bllms?\b|generative ai|\bgen ?ai\b|large language|\brag\b|langchain|llamaindex", "TensorFlow": r"tensorflow", "PyTorch": r"pytorch",
    "Scikit-learn": r"scikit|sklearn", "Pandas": r"\bpandas\b", "ETL": r"(?-i:\bETL\b|\bELT\b)", "Data Warehouse": r"data ?warehous|kho dữ liệu|(?-i:\bDWH\b)",
    "Data Modeling": r"data model(?:l?ing)?\b|mô hình hóa dữ liệu", "Spark": r"\bspark\b", "Hadoop": r"hadoop|\bhive\b|\bhdfs\b",
    "Kafka": r"\bkafka\b", "Flink": r"\bflink\b", "Airflow": r"airflow", "dbt": r"(?-i:\bdbt\b)", "Snowflake": r"snowflake",
    "BigQuery": r"bigquery", "Databricks": r"databricks", "Redshift": r"redshift", "SSIS": r"(?-i:\bSSIS\b)", "Informatica": r"informatica",
    "Talend": r"\btalend\b", "NoSQL": r"nosql|mongodb|cassandra|elasticsearch", "AWS": r"(?-i:\bAWS\b)|amazon web services",
    "Azure": r"\bazure\b", "GCP": r"(?-i:\bGCP\b)|google cloud", "Docker": r"\bdocker\b", "Kubernetes": r"kubernetes|\bk8s\b",
    "MLOps": r"mlops", "Git": r"\bgit(?:hub|lab)?\b", "Linux": r"\blinux\b", "Java": r"\bjava\b(?!\s*script)", "Scala": r"\bscala\b",
    "SAS": r"(?-i:\bSAS\b)", "SPSS": r"\bspss\b", "A/B Testing": r"\ba/?b test",
    "Power Query / DAX": r"power query|(?-i:\bDAX\b)", "Google Sheets": r"google sheets?|\bgg ?sheets?\b",
    "Data Governance": r"data governance|quản trị dữ liệu", "Data Quality": r"data quality|chất lượng dữ liệu",
    # quant
    "C++": r"(?<!\w)c\+\+", "MATLAB": r"\bmatlab\b", "Stata / EViews": r"\bstata\b|\beviews\b",
    "Kinh tế lượng": r"econometric|kinh tế lượng", "Chuỗi thời gian": r"time[- ]series|chuỗi thời gian",
    "Stochastic / Monte Carlo": r"stochastic|monte carlo|giải tích ngẫu nhiên",
    "Mô hình rủi ro": r"(?:risk|credit|pricing) model|credit scor|scorecard|mô hình (?:rủi ro|tín dụng|chấm điểm)|basel|ifrs ?9|(?-i:\bLGD\b|\bVaR\b)",
    "Định giá phái sinh": r"derivatives? (?:pricing|trading|products?|markets?)|option pricing|black[- ]scholes|phái sinh",
    "Bloomberg": r"\bbloomberg\b",
    "Tiếng Anh": r"tiếng anh|\benglish (?:skill|proficien|communication|speaking|writing|fluen|level)|(?:fluent|good|proficient|proficiency|competent) (?:in )?english|ielts|toeic|toefl",
    "Tiếng Nhật": r"tiếng nhật|japanese|\bjlpt\b",
}
SKILLS = {name: re.compile(pat, re.I) for name, pat in SKILLS.items()}
# chương trình Management Trainee / Graduate: tên không ghi "data" → chỉ giữ khi tin đòi kỹ năng data
TRAINEE_RE = re.compile(r"management trainee|quản trị viên tập sự|qtv tập sự|\bMT\b|\btrainee\b|tập sự"
                        r"|graduate (?:development )?(?:program|trainee|scheme)|future leader"
                        r"|young (?:talent|leader)|fast[- ]track|leadership (?:development )?program|tài năng trẻ", re.I)
DATA_SKILLS = {"SQL", "R", "Power BI", "Tableau", "Looker", "Qlik", "Machine Learning", "Deep Learning", "ETL", "Data Warehouse",
               "Spark", "BigQuery", "Snowflake", "Databricks", "SAS", "SPSS"}


def is_data_job(text):
    if not DATA_RE.search(text) or NOT_DATA_RE.search(text):
        return False
    return not OTHER_ROLE_RE.search(text) or bool(DATA_ROLE_RE.search(text))


def is_data_program(j):
    """'Management Trainee 2026', 'Graduate Program', 'Aeon Future Leader'... mà tin đòi SQL/Python/Power BI → giữ."""
    if not TRAINEE_RE.search(j["title"]) or NOT_DATA_RE.search(j["title"]) or OTHER_ROLE_RE.search(j["title"]):
        return False
    return bool(DATA_SKILLS & set(j.get("skills", [])))  # nhãn kỹ năng của nguồn quá rộng ("Excel Data Handling") nên không dùng


def keep(j):
    return is_data_job(j["title"]) or is_data_program(j)


def skills(text):
    """Kỹ năng nhắc trong tin, theo thứ tự xuất hiện."""
    found = {name: m.start() for name, pat in SKILLS.items() if (m := pat.search(text))}
    return sorted(found, key=found.get)


def levels(title, hint="", years=None):
    """Tên vị trí → cấp bậc. Tên không ghi thì dùng nhãn cấp bậc của nguồn, cuối cùng là số năm kinh nghiệm tối thiểu."""
    for text in (title, hint or ""):
        if found := [k for k, pat in LEVELS.items() if re.search(pat, text, re.I)]:
            return found
    if years is not None:
        return ["intern" if years == 0 else "junior" if years <= 1 else "mid" if years < 5 else "senior"]
    return []


_N = r"(?<![\d.,])(\d{1,2})(?:\s*(?:-|–|~|to|đến|tới)\s*(\d{1,2}))?\s*\+?"  # "3", "2 - 3", "3–5+", "02"
EXP_RE = re.compile(
    # 3+ years of (relevant) experience, 5 years and above practical experience, 2+ years of hands-on BI/Data Analyst experience, 3-year experience
    rf"{_N}[\s-]*(?:years?|yrs?)['’]?\s*(?:of\s*)?(?:[\w/-]+\s+){{0,4}}?experience"
    rf"|experiences?\s*[:\-–]?\s*(?:of\s+|from\s+|at least\s+|minimum(?: of)?\s+)?{_N}\s*(?:years?|yrs?)\b"  # Experience: 3-5 years, Experiences3 Years
    rf"|{_N}\s*năm\s+kinh nghiệm"  # tối thiểu 1 - 2 năm kinh nghiệm
    rf"|kinh nghiệm[^.;•\n]{{0,50}}?{_N}\s*năm\b",  # Kinh nghiệm: Từ 3 năm; kinh nghiệm ở vị trí tương đương tối thiểu 01 năm
    re.I)
# mỗi cấp một mức: "3 năm (CVCC)/ 2 năm (CVC)/ 1 năm (CV) kinh nghiệm", "Từ 2 năm (Middle) đến 4+ năm (Senior) kinh nghiệm",
# "3 years (Senior Officer)/2 years (Officer) of working experience" → khoảng từ mức thấp nhất tới cao nhất
MULTI_EXP_RE = re.compile(r"(?:(?<![\d.,])\d{1,2}\+?\s*(?:năm|years?)\s*\([^()]{1,40}\)[\s/,;]*(?:đến|hoặc|or|và|and)?\s*){2,}"
                          r"(?:of\s+)?(?:[\w-]+\s+){0,2}?(?:kinh nghiệm|experience)", re.I)
# "chưa có kinh nghiệm" chỉ tính khi kèm "được đào tạo": "NLĐ học việc mà chưa có kinh nghiệm" là chính sách, không phải yêu cầu
NO_EXP_RE = re.compile(r"không (?:yêu cầu|cần|đòi hỏi) kinh nghiệm|chưa có kinh nghiệm (?:sẽ |vẫn )?được|no (?:prior |previous )?experience (?:is )?(?:required|needed)", re.I)


def experience(text):
    """Số năm kinh nghiệm yêu cầu, lấy chỗ nhắc đầu tiên (thường là yêu cầu chính) → (ít nhất, nhiều nhất hoặc None); không ghi → None.
    '2 - 3 năm kinh nghiệm' → (2, 3), '5+ years of experience' → (5, None), 'Dưới 1 năm' / 'up to 1 year' → (0, 1), 'Không yêu cầu kinh nghiệm' → (0, None)."""
    text = text or ""
    multi = MULTI_EXP_RE.search(text)
    for m in EXP_RE.finditer(text):
        if multi and multi.start() < m.start():  # mỗi cấp một mức, nhắc trước
            break
        lo, hi = ([int(g) for g in m.groups() if g is not None] + [None])[:2]
        if lo > 25:  # "30+ years of engineering execution" = tuổi công ty
            continue
        if re.search(r"(?:dưới|under|less than|up to|tối đa)\s*$", text[max(0, m.start() - 12):m.start()], re.I):
            lo, hi = 0, lo
        return lo, (hi if hi and lo < hi <= 25 else None)
    if multi:
        ys = [int(y) for y in re.findall(r"(\d{1,2})\+?\s*(?:năm|years?)", multi[0], re.I)]
        return min(ys), max(ys)
    return (0, None) if NO_EXP_RE.search(text) else None


def exp_label(lo, hi):
    """(2, 3) → '2–3 năm', (5, None) → '5+ năm', (0, None) → 'Không yêu cầu'. Trang web thêm chữ 'kinh nghiệm'."""
    return f"{lo}–{hi} năm" if hi and hi > lo else f"{lo}+ năm" if lo else "Không yêu cầu"


def read(j, full):
    """Mô tả đầy đủ → kỹ năng, số năm kinh nghiệm; tên vị trí, nguồn không ghi cấp bậc thì suy từ số năm.
    Số năm do nguồn ghi sẵn (job(exp=...)) được ưu tiên hơn số đọc từ mô tả."""
    text = f"{j['title']} {full}"
    j["skills"] = skills(text)
    if not j.get("exp") and (e := experience(text)):
        j["exp"] = exp_label(*e)
        j["level"] = j.get("level") or levels("", "", e[0])


# lương ghi trong tên tin: "( Thu nhập 45-55M)", "Lương Up To 40M + Thưởng", "- Up to $2500". Phải có số ngay sau:
# "Thu nhập hấp dẫn", "Lương tháng 13" không phải mức lương.
TITLE_SALARY_RE = re.compile(r"(?:lương|thu nhập|salary|(?=up ?to\s*\$))\s*:?\s*((?:up ?to|tới|đến|lên (?:đến|tới)|từ|trên)?\s*\$?\s*\d[\d.,]*"
                             r"\s*(?:[-–~]\s*\$?\s*\d[\d.,]*)?\s*(?:triệu|tr\b|m\b|k\b|usd|vnđ|vnd)?)", re.I)


def get(url, body=None):
    """Scrapling giả lập Chrome tới cả dấu vân tay TLS (không chỉ header) → Cloudflare của TopCV, JobsGo... không coi là bot.
    body: dict → gửi POST JSON."""
    headers = {"Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8"}
    for wait in (30, 90, 0):  # 429 = gửi quá nhiều request (LinkedIn hay chặn IP máy chủ GitHub) → chờ rồi thử lại
        r = Fetcher.get(url, headers=headers) if body is None else Fetcher.post(url, json=body, headers=headers)
        if r.status != 429 or not wait:
            break
        time.sleep(wait)
    if r.status >= 400:
        raise urllib.error.HTTPError(url, r.status, r.reason, None, None)
    return r.body.decode("utf-8")


def get_json(url, body=None):
    return json.loads(get(url, body))


def soup(url):
    return BeautifulSoup(get(url), "html.parser")


def text(node, css, sep=" "):
    el = node.select_one(css)
    return el.get_text(sep, strip=True) if el else ""


def day(v):
    """ISO string, epoch hoặc kiểu Date của JavaScript ('Sat Oct 10 2026 ...') → 'YYYY-MM-DD'."""
    if not v:
        return TODAY
    if str(v).isdigit():
        return datetime.fromtimestamp(int(v), timezone.utc).date().isoformat()
    if re.match(r"[A-Z][a-z]{2} [A-Z][a-z]{2} \d", str(v)):
        return datetime.strptime(str(v)[4:15], "%b %d %Y").date().isoformat()
    return str(v)[:10]


def ago(s):
    """'Posted 3 Days Ago' / 'Đăng 2 tuần trước' / '9 giờ trước' / 'Posted Yesterday' → ngày đăng."""
    if re.search(r"yesterday|hôm qua", s, re.I):
        return (date.today() - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\+?\s*(minute|hour|day|week|month|phút|giờ|ngày|tuần|tháng)", s, re.I)
    if not m:
        return TODAY
    unit = {"minute": 0, "phút": 0, "hour": 0, "giờ": 0, "day": 1, "ngày": 1, "week": 7, "tuần": 7, "month": 30, "tháng": 30}
    return (date.today() - timedelta(days=int(m[1]) * unit[m[2].lower()])).isoformat()


BLOCKS = ["p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article"]


def lines(markup):
    """Mô tả HTML hoặc chữ → các dòng (đoạn văn, mục danh sách), bỏ dấu đầu dòng. Giữ cấu trúc để chia mục (sections).
    '• a • b' trên cùng một dòng tách thành hai ý; đoạn dài không xuống dòng (TalentNetwork, Vieclam24h) tách theo câu, theo '1. 2.';
    dòng bắt đầu bằng chữ thường mà dòng trước chưa hết câu là chữ bị ngắt dòng cứng (MoMo) → nối lại."""
    s = BeautifulSoup(markup or "", "html.parser")
    for t in s.find_all(BLOCKS):  # \0 = ranh giới thẻ khối, không nối qua
        t.insert_before("\0")
        t.insert_after("\0")
    for br in s.find_all("br"):  # <br> = xuống dòng mềm: SHB, PVcomBank ngắt cả giữa câu
        br.replace_with("\n")
    out = []
    for block in s.get_text().split("\0"):
        rows = []
        for line in block.splitlines():
            pieces = re.split(r"\s[•●▪◦■➢➤►✓✔]\s*", line)
            if len(line) > 200:
                pieces = [x for p in pieces for x in re.split(r"(?<=[^\d\s][.!?;])\s+(?:[-–]\s+)?|\s(?=\d{1,2}\.\s)", p)]  # "1." không phải hết câu
            for p in pieces:
                p = " ".join(p.split()).lstrip("-–•●▪◦·*+✓✔➢➤►>■ ")
                if rows and p[:1].islower() and not rows[-1].endswith((".", ":", "!", "?")):  # "hằng ngày; chủ động..." vẫn một câu
                    rows[-1] += " " + p
                elif p:
                    rows.append(p)
        out += rows
    return out


def short(t, n=400):
    """Đoạn văn ngắn cho khung xem nhanh."""
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


# tiêu đề trong mô tả tin → mục trên khung xem nhanh. Mỗi mục: (tiêu đề rõ ràng, tiêu đề phụ: chỉ tính khi có ":" hoặc viết hoa,
# vì "Lương tháng 13", "Kinh nghiệm làm việc với Spark" là một ý chứ không phải tiêu đề). Mục "" = bỏ: giới thiệu công ty, cách nộp hồ sơ...
SECTIONS = {
    "Mô tả công việc": (r"mô tả công việc|job description|(?:key |main )?responsibilit|what you(?:'ll| will) do|your (?:role|mission)"
                        r"|the (?:role|job)\b|about the (?:role|job)|nội dung công việc|công việc chính|nhiệm vụ chính|duties|key accountabilit",
                        r"mô tả|description|nhiệm vụ|trách nhiệm|vai trò|mục tiêu"),
    "Yêu cầu": (r"yêu cầu|requirement|qualification|tiêu chuẩn|what (?:we(?:'re| are) looking for|you(?:'ll| will)? (?:need|bring))"
                r"|(?:your )?(?:skills?|qualifications?) (?:and|&) (?:experience|qualifications?)|must[- ]have|nice[- ]to[- ]have|who you are|ứng viên phù hợp",
                r"kỹ năng|kinh nghiệm|trình độ|điều kiện|năng lực|skills|experience"),
    "Quyền lợi": (r"quyền lợi|(?:\w+ )?benefits?\b|phúc lợi|đãi ngộ|why (?:you'll love|join)|(?:top \d+ )?reasons to join|what we offer|we offer|perks",
                  r"chế độ|thu nhập|lương|compensation"),
    "": (r"thông tin khác|hồ sơ|cách (?:thức )?ứng tuyển|how to apply|liên hệ|about us|về chúng tôi|giới thiệu|who we are|equal opportunit",
         r"thời gian làm việc|địa điểm làm việc|working (?:time|hours|location)|contact"),
}
SECTIONS = {name: (re.compile(s), re.compile(w)) for name, (s, w) in SECTIONS.items()}


def heading(line):
    """Dòng là tiêu đề mục → tên mục ("" = mục bỏ đi); không phải tiêu đề → None. '2. YÊU CẦU CÔNG VIỆC:' → 'Yêu cầu'."""
    words = len(line.split())
    if words > 7 or ":" in line.rstrip(" :"):  # "Kinh nghiệm: 2 năm" là nội dung
        return None
    key = re.sub(r"^(?:[\dIVX]{1,4}[.)/]|[^\w\s])+\s*", "", line).rstrip(" :").lower()  # bỏ "1.", "II.", "★"
    for name, (strong, weak) in SECTIONS.items():
        if strong.match(key) or weak.match(key) and (line.rstrip().endswith(":") or line.isupper()):
            return name
    return None


def sections(text_lines, items=8, width=200):
    """Các dòng mô tả → [[tên mục, [ý...]], ...] cho khung xem nhanh: Mô tả công việc, Yêu cầu, Quyền lợi.
    Phần trước tiêu đề đầu tiên: là mô tả công việc nếu tin không có mục đó (nhiều trang VN), không thì là giới thiệu công ty (LinkedIn).
    Mỗi mục tối đa `items` ý, mỗi ý `width` ký tự → jobs.json không phình."""
    out, cur = {}, None
    for line in text_lines:
        if (h := heading(line)) is not None:  # tiêu đề phụ cùng mục ("Key Responsibilities", "Must Have") cũng bỏ, không thành một ý
            cur = h
        elif cur != "":
            out.setdefault(cur, []).append(short(line, width))
    intro = out.pop(None, [])
    if intro:
        out["Giới thiệu" if "Mô tả công việc" in out else "Mô tả công việc"] = intro
    out["Giới thiệu"] = out.get("Giới thiệu", [])[:3]
    order = ["Giới thiệu", "Mô tả công việc", "Yêu cầu", "Quyền lợi"]  # ITviec đặt "Top 3 Reasons To Join Us" lên đầu
    return [[name, out[name][:items]] for name in order if out.get(name)]


_RATES = {}  # số đơn vị tiền mỗi 1 USD, lấy 1 lần mỗi lần chạy


def rate(cur):
    """Số VNĐ cho 1 đơn vị ngoại tệ, theo tỷ giá hiện tại (open.er-api.com: miễn phí, cập nhật hằng ngày)."""
    if not _RATES:
        _RATES.update(get_json("https://open.er-api.com/v6/latest/USD")["rates"])
    return _RATES["VND"] / _RATES[cur]


def vnd(s):
    """Mọi kiểu ghi lương → triệu VNĐ/tháng:
    '$ 1,500-2,500 /tháng' → '≈39–65 triệu' (≈ = quy đổi từ ngoại tệ), '14 - 15,5 Triệu VND' → '14–15,5 triệu',
    '20tr-25tr ₫/tháng' → '20–25 triệu', 'Tới 35 triệu' → 'Đến 35 triệu', 'Thương lượng' / 'Cạnh tranh' → 'Thỏa thuận'."""
    s = (s or "").strip()
    if not s:
        return ""
    if not re.search(r"\d", s):
        return "Thỏa thuận"
    low = s.lower()
    code = re.search(r"\b(?!VND)([A-Z]{3})\b", s.upper())  # "1000-2000 USD", "SGD 5,000"
    cur = "USD" if "$" in s else "EUR" if "€" in s else code[1] if code and code[1] in ("USD", "EUR", "SGD", "JPY", "GBP", "AUD", "KRW") else "VND"
    if cur == "VND" and re.search(r"triệu|\d\s*(?:tr|m)\b", low):  # số đã tính bằng triệu, dấu phẩy là thập phân
        nums = [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", s)]
    else:  # "1,500" / "15.000.000" / "60k": dấu phẩy, chấm là phân cách hàng nghìn
        nums = [float(re.sub(r"[.,](?=\d{3}\b)", "", n.rstrip("kK"))) * (1000 if n[-1] in "kK" else 1)
                for n in re.findall(r"\d[\d.,]*[kK]?", s)]
        nums = [n * rate(cur) / 1e6 for n in nums]
    nums = list(dict.fromkeys(n for n in nums if n))
    if nums and (re.search(r"năm|year|annual", low) or max(nums) > 500 and "tháng" not in low):  # lương năm ("$60K – $90K")
        nums = [n / 12 for n in nums]
    if not nums or max(nums) < 0.5 or max(nums) > 2000:  # dữ liệu nguồn sai (vd 1–2 USD) → bỏ
        return ""
    approx = "≈" if cur != "VND" or "≈" in s else ""
    fmt = lambda n: (f"{n:.0f}" if approx else f"{round(n, 1):g}").replace(".", ",")  # quy đổi thì làm tròn, VNĐ gốc giữ số lẻ
    prefix = "Đến " if re.match(r"(tới|đến|lên đến|lên tới|up ?to)", low) else "Từ " if re.match(r"(từ|trên|from)", low) else ""
    return f"{prefix}{approx}{'–'.join(fmt(n) for n in nums[:2])} triệu"


def job(title, company, location, region, url, source, posted, logo="", salary="", tags=(), desc="", hint="", exp=None, raw=None):
    """desc: mô tả đầy đủ (HTML hoặc chữ), kỹ năng đọc từ đây. Tin không kèm mô tả thì run() đọc trang chi tiết (details).
    hint: nhãn cấp bậc của nguồn ("Senior", "Trưởng phòng"...), exp: số năm kinh nghiệm nguồn ghi sẵn (ít nhất, nhiều nhất hoặc None).
    raw: bản ghi gốc của nguồn (dict từ API, thẻ tin HTML, mục RSS). Cùng full, salary_raw chỉ lưu vào kho (ARCHIVE_ONLY)."""
    rows = lines(desc)
    full = "\n".join(rows)  # kho giữ xuống dòng: chia lại mục được khi sửa SECTIONS
    exp = exp or experience(f"{title} {full}")
    if not str(salary or "").strip() and (m := TITLE_SALARY_RE.search(title)):
        salary = m[1]
    extra = dict(logo=logo, salary=vnd(salary), tags=list(tags)[:6], desc=short(" ".join(rows)), exp=exp and exp_label(*exp),
                 level=levels(title, hint, exp and exp[0]))
    j = dict(title=title.strip(), company=(company or "").strip(), location=(location or "").strip(),
             region=region, url=url, source=source, date=posted, **{k: v for k, v in extra.items() if v})
    if len(full) > 400:  # mô tả thật, không phải tóm tắt vài dòng
        read(j, full)  # skills, sections có mặt (kể cả rỗng) = đã đọc, run() không đọc trang chi tiết nữa
        j["full"] = full
        j["sections"] = sections(rows)
    if str(salary or "").strip():
        j["salary_raw"] = str(salary).strip()  # "$ 1,500-2,500 /tháng" trước khi quy đổi
    if raw is not None:
        j["raw"] = (raw.get_text(" ", strip=True) if hasattr(raw, "get_text")  # thẻ tin HTML: mọi chữ trên thẻ (hạn nộp, loại hình...)
                    else {e.tag: e.text for e in raw} if isinstance(raw, ET.Element) else raw)
    return j


PAGES = 3  # số trang đọc ở mỗi trang tuyển dụng (tin mới nằm ở đầu)


def amount(lo, hi, cur="VND"):
    """Khoảng lương dạng số → '14000000-18000000 VND' để job() quy đổi sang triệu VNĐ."""
    return f"{lo}-{hi} {cur}" if lo and hi else f"Đến {hi} {cur}" if hi else f"Từ {lo} {cur}" if lo else ""


# ---------- Việt Nam ----------

def vietnamworks():
    out = []
    # trainee, tập sự: chương trình MT (is_data_program). Tìm theo cả mô tả nên "quantitative" ra nhiều tin khác, tên tin lọc lại sau.
    for q in ("data", "dữ liệu", "BI", "machine learning", "quantitative", "actuarial", "trainee", "tập sự"):
        d = get_json("https://ms.vietnamworks.com/job-search/v1.0/search", {"query": q, "page": 0, "hitsPerPage": 100})
        for j in d["data"]:
            loc = ", ".join(l.get("cityNameVI") or l.get("cityName", "") for l in j.get("workingLocations") or [])
            years = j.get("yearsOfExperience") or 0  # -1, 0 = không ghi → đọc từ mô tả
            out.append(job(j["jobTitle"], j["companyName"], loc, "VN", j["jobUrl"], "VietnamWorks", day(j["approvedOn"]),
                           logo=j.get("companyLogo") or "", salary=j.get("prettySalary"),  # nhãn kỹ năng do nhà tuyển dụng tự gõ, mơ hồ → đọc từ mô tả
                           desc=f"<h4>Mô tả công việc</h4>{j.get('jobDescription') or ''}<h4>Yêu cầu</h4>{j.get('jobRequirement') or ''}"
                                f"<h4>Quyền lợi</h4>" + "".join(f"<p>{b.get('benefitValue') or b.get('benefitNameVI') or ''}</p>" for b in j.get("benefits") or []),
                           hint=j.get("jobLevelVI"), exp=(years, None) if years > 0 else None, raw=j))
    return out


def careerviet():
    out = []
    for c in (c for kw in ("data", "quant", "actuarial") for c in soup(f"https://careerviet.vn/viec-lam/{kw}-k-vi.html").select("div.job-item")):
        a = c.select_one("a.job_link")
        m = re.search(r"Cập nhật\s*:\s*(\d\d)-(\d\d)-(\d{4})", c.get_text(" ", strip=True))
        img = c.select_one("img.image-logo-emp")
        src = img.get("src", "") if img else ""  # /_next/image?url=<ảnh gốc>&w=...
        out.append(job(a["title"], text(c, "a.company-name"), text(c, "div.location", ", "), "VN",
                       urllib.parse.urljoin("https://careerviet.vn", a["href"]), "CareerViet",
                       f"{m[3]}-{m[2]}-{m[1]}" if m else TODAY,
                       logo=urllib.parse.parse_qs(urllib.parse.urlparse(src).query).get("url", [src])[0],
                       salary=re.sub(r"^Lương:\s*", "", text(c, "div.salary")), raw=c))
    return out


class RateLimited(Exception):
    """Nguồn tạm thời chặn vì gửi quá nhiều request: không tính là hỏng (workflow không báo đỏ), tin cũ vẫn giữ, lần chạy sau thử lại."""


def linkedin():
    """API công khai của LinkedIn Jobs, không cần đăng nhập."""
    out = []
    for kw, start in [("data", 0), ("data", 25), ("data", 50), ("data", 75), ("management trainee", 0), ("quantitative", 0)]:
        q = urllib.parse.urlencode({"keywords": kw, "location": "Vietnam", "sortBy": "DD", "start": start})
        try:
            cards = soup(f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?{q}").select("div.base-search-card")
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            if not out:
                raise RateLimited("429 Too Many Requests") from e
            break  # bị giới hạn tốc độ giữa chừng → giữ các trang đã lấy được
        for c in cards:
            job_id = c.get("data-entity-urn", "").rsplit(":", 1)[-1]
            t = c.select_one("time")
            img = c.select_one("img[data-delayed-url]")
            out.append(job(text(c, "h3"), text(c, "h4"), text(c, ".job-search-card__location"), "VN",
                           f"https://www.linkedin.com/jobs/view/{job_id}", "LinkedIn", t["datetime"] if t else TODAY,
                           logo=img["data-delayed-url"] if img else "", salary=text(c, ".job-search-card__salary-info"), raw=c))
        time.sleep(5)  # tránh bị LinkedIn chặn (429)
    return out


def slugify(s):
    """'Phân tích Dữ liệu' → 'phan-tich-du-lieu' (cho link trang chỉ cần id, slug để link dễ đọc)."""
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


YBOX_CITY = {"HN": "Hà Nội", "HCM": "Hồ Chí Minh", "ĐN": "Đà Nẵng", "DN": "Đà Nẵng"}


def ybox_title(t):
    """'[HN/HCM] Công Ty X Tuyển Dụng Thực Tập Sinh Data Analyst, Nhân Viên Sales Full-time 2026'
    → ('Hà Nội, Hồ Chí Minh', 'Công Ty X', 'Thực Tập Sinh Data Analyst'). Một bài thường tuyển nhiều vị trí → chỉ giữ vị trí ngành data."""
    m = re.match(r"\s*(?:\[([^\]]*)\])?\s*(?:(.*?)\s+tuyển dụng\s+)?(.*)", t, re.I)
    where, company, roles = m[1] or "", m[2] or "", m[3]
    roles = re.sub(r"\s+[\w/-]*(?:part-time|full-time|remote)[\w/ -]*\b20\d\d\b.*$", "", roles, flags=re.I)  # bỏ "Full-time 2026"
    data_roles = [r for r in re.split(r",\s*(?![^()]*\))", roles) if is_data_job(r)]  # tách theo dấu phẩy ngoài ngoặc
    loc = ", ".join(YBOX_CITY.get(c.strip(), c.strip()) for c in re.split(r"[/-]", where) if c.strip())
    return loc, company, ", ".join(data_roles) or roles


def ybox():
    """Ybox.vn (nhiều tin thực tập/fresher, ít tin data): API GraphQL công khai mà chính trang dùng. ~50 bài tuyển dụng/ngày."""
    out = []
    for page in range(1, 5):  # 200 bài mới nhất ≈ 4 ngày, chạy 6 tiếng/lần là đủ
        q = ('{ AllPosts { NewestPosts(limit: 50, page: %d, communityId: "5a4542f355ae5009afa5a3ec") '
             "{ edges { _id title publishedAt photo summary } } } }" % page)
        for p in get_json("https://api.ybox.vn/graphql?query=" + urllib.parse.quote(q))["data"]["AllPosts"]["NewestPosts"]["edges"]:
            loc, company, title = ybox_title(p["title"])
            out.append(job(title, company, loc, "VN", f"https://ybox.vn/tuyen-dung/{slugify(p['title'])}-{p['_id']}", "Ybox", day(p["publishedAt"]),
                           logo=(p.get("photo") or "").replace("http://", "https://"), desc=p.get("summary"), raw=p))
    return out


def topdev():
    fields = ("fields[job]=id,title,company,addresses,detail_url,published,job_levels_str,skills_str"
              "&fields[company]=display_name,image_logo")
    out = []
    for page in range(1, PAGES + 1):
        d = get_json(f"https://api.topdev.vn/td/v2/jobs?keyword=data&page={page}&page_size=50&{fields}")
        for j in d["data"]:
            dd, mm, yy = j["published"]["date"].split("-")  # "02-10-2026"
            out.append(job(j["title"], j["company"]["display_name"], j["addresses"].get("sort_addresses", ""), "VN",
                           j["detail_url"], "TopDev", f"{yy}-{mm}-{dd}", logo=j["company"].get("image_logo") or "",
                           tags=[t for t in (j.get("skills_str") or "").split(", ") if t], hint=j.get("job_levels_str"), raw=j))
        if page >= d["meta"]["last_page"]:
            break
    return out


def glints():
    logo = "https://images.glints.com/unsafe/glints-dashboard.oss-ap-southeast-1-internal.aliyuncs.com/company-logo/"
    out = []
    for kw in ("data", "quant"):
        for page in range(1, PAGES + 1):
            d = next_data(f"https://glints.com/vn/opportunities/jobs/explore?keyword={kw}&country=VN&page={page}")["initialJobs"]
            for j in d["jobsInPage"]:
                loc = j.get("location") or {}
                sal = (j.get("salaries") or [{}])[0] if j.get("shouldShowSalary") else {}
                lo, hi = j.get("minYearsOfExperience"), j.get("maxYearsOfExperience")  # (0, 50) = không giới hạn → đọc từ mô tả
                out.append(job(j["title"], j["company"]["name"], ((loc.get("parents") or [{}])[0].get("name") or loc.get("name", "")), "VN",
                               f"https://glints.com/vn/opportunities/jobs/{slugify(j['title'])}/{j['id']}", "Glints", day(j["updatedAt"]),
                               logo=logo + j["company"]["logo"] if j["company"].get("logo") else "",
                               salary=amount(sal.get("minAmount"), sal.get("maxAmount"), sal.get("CurrencyCode") or "VND"),
                               exp=(lo, hi) if lo is not None and hi and hi <= 25 else None, raw=j))
            if not d.get("hasMore"):
                break
    return out


# ---------- Trang tuyển dụng của công ty ----------
# Nhiều công ty dùng hệ thống tuyển dụng (ATS) có API công khai → mỗi hàm dưới đây đọc được mọi công ty dùng hệ thống đó.
# Chỉ lấy tin ở Việt Nam. Danh sách công ty: COMPANIES ở cuối phần này.
COMPANY_SOURCE = "Trang công ty"
VN_RE = re.compile(r"viet ?nam|việt nam|ha ?noi|hà nội|ho chi minh|hồ chí minh|\bhcm|sai ?gon|da ?nang|đà nẵng|binh duong|bình dương"
                   r"|hai phong|hải phòng|bac ninh|bắc ninh|can tho|cần thơ", re.I)


def greenhouse(slug, name):
    return [job(j["title"], name, j["location"]["name"], "VN", j["absolute_url"], COMPANY_SOURCE,
                day(j.get("first_published") or j["updated_at"]), desc=html.unescape(j.get("content") or ""), raw=j)
            for j in get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")["jobs"]
            if VN_RE.search(j["location"]["name"])]


def lever(slug, name):
    return [job(j["text"], name, j["categories"].get("location", ""), "VN", j["hostedUrl"], COMPANY_SOURCE,
                day(str(j["createdAt"] // 1000)), raw=j,  # lists = các mục "What you'll do", "Requirements"...
                desc=(j.get("description") or "") + "".join(f"<h4>{l.get('text', '')}</h4>{l.get('content', '')}" for l in j.get("lists") or [])
                     + (j.get("additional") or ""))
            for j in get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
            if j.get("country") == "VN" or VN_RE.search(j["categories"].get("location", ""))]


def ashby(slug, name):
    out = []
    for j in get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")["jobs"]:
        country = ((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry", "")
        locs = [j.get("location", ""), country] + [l.get("location", "") for l in j.get("secondaryLocations") or []]
        if loc := next((l for l in locs if VN_RE.search(l)), None):
            out.append(job(j["title"], name, loc, "VN", j["jobUrl"], COMPANY_SOURCE, day(j["publishedAt"]),
                           salary=(j.get("compensation") or {}).get("compensationTierSummary"), desc=j.get("descriptionHtml") or j.get("descriptionPlain"), raw=j))
    return out


def smartrecruiters(slug, name):
    out = []
    for offset in range(0, 500, 100):
        d = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?country=vn&limit=100&offset={offset}")
        for j in d["content"]:
            loc = j["location"]
            out.append(job(j["name"], name, loc.get("city") or loc.get("region") or "Vietnam", "VN",
                           f"https://jobs.smartrecruiters.com/{j['company']['identifier']}/{j['id']}", COMPANY_SOURCE,
                           day(j["releasedDate"]), hint=(j.get("experienceLevel") or {}).get("label"), raw=j))
        if offset + 100 >= d["totalFound"]:
            break
    return out


def workday(board, name):
    """Workday (NVIDIA, Intel, Unilever...): board = '<mã>.wd<N>/<trang>' trong link <mã>.wd<N>.myworkdayjobs.com/<trang>.
    Bộ lọc quốc gia mỗi công ty đặt một kiểu → tìm chữ "Vietnam", rồi đọc chi tiết các tin ngành data để biết chắc quốc gia,
    ngày đăng và mô tả (danh sách chỉ ghi "2 Locations", "Posted 30+ Days Ago")."""
    host, site = board.split("/")
    api = f"https://{host}.myworkdayjobs.com/wday/cxs/{host.split('.')[0]}/{site}"
    out, total = [], 0
    for offset in range(0, 500, 20):  # tối đa 20 tin/lần
        d = get_json(f"{api}/jobs", {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": "Vietnam"})
        total = total or d["total"]  # từ trang 2 Workday trả total = 0
        for j in d["jobPostings"]:
            if not (is_data_job(j.get("title", "")) or TRAINEE_RE.search(j.get("title", ""))):  # có tin ẩn chỉ còn mã tin, không có tên
                continue
            info = get_json(api + j["externalPath"])["jobPostingInfo"]
            locs = [info.get("location", "")] + info.get("additionalLocations", [])
            if VN_RE.search((info.get("country") or {}).get("descriptor", "")) or any(VN_RE.search(l) for l in locs):
                out.append(job(info["title"], name, " / ".join(l for l in locs if VN_RE.search(l)) or locs[0], "VN", info["externalUrl"],
                               COMPANY_SOURCE, info.get("startDate") or ago(j.get("postedOn", "")), desc=info.get("jobDescription"), raw=info))
        if offset + 20 >= total:
            break
    return out


def successfactors(base, name, keywords=("data", "dữ liệu", "analytics", "Business Intelligence", "AI", "machine learning",
                                         "quant", "định lượng", "mô hình", "trainee", "tập sự")):
    """SAP SuccessFactors (VPBank, Techcombank, Vietcombank, Sacombank...) có RSS. Tiêu đề dạng 'Tên vị trí (Hà Nội, VN)'.
    ponytail: RSS trả tối đa 20 tin mới nhất mỗi từ khóa; công ty tuyển >20 vị trí data cùng lúc thì thêm từ khóa hẹp hơn."""
    out = []
    for kw in keywords:
        for it in ET.fromstring(get(f"{base}/services/rss/job/?locale=vi_VN&keywords=({urllib.parse.quote(kw)})")).iter("item"):
            m = re.match(r"(.*?)\s*\(([^()]*), VN\)\s*$", it.findtext("title"))
            title, loc = (m[1], m[2]) if m else (it.findtext("title"), "")
            pub = it.findtext("pubDate")  # có tin không ghi ngày đăng → ngày thấy lần đầu
            out.append(job(title, name, loc, "VN", it.findtext("link"), COMPANY_SOURCE,
                           parsedate_to_datetime(pub).date().isoformat() if pub else TODAY, desc=it.findtext("description"), raw=it))
    return out


def ainavi(domain, name):
    """Ainavi (TPBank, OCB, LPBank, Nam A Bank, NCB, VietABank...): trang tuyển dụng có ảnh từ centralize-api.ainavi.com.vn,
    link tin dạng <domain>/vi/jobs/<mã>. API chung của nền tảng, lọc theo tên miền trang tuyển dụng."""
    out = []
    for page in range(1, 20):
        d = get_json(f"https://centralize-api.ainavi.com.vn/api/recruitment/Recruitment/GetRecruitmentsByDomain"
                     f"?pageIndex={page}&pageSize=50&Domain={domain}")  # tối đa 50 tin/trang
        for j in d["items"]:
            posted = (j.get("recruitmentPublish") or {}).get("statTime") or j["createdTime"]  # giờ UTC, 17:00Z = 0h hôm sau ở VN
            lo, hi = j.get("minSalary"), j.get("maxSalary")
            places = [a.get("provinceName") for a in (j.get("workingNewAddresses") or []) + (j.get("workingAddresses") or [])]
            out.append(job(j["name"], name, ", ".join(dict.fromkeys(p for p in places if p)), "VN", f"https://{domain}/vi/jobs/{j['slug']}", COMPANY_SOURCE,
                           (datetime.fromisoformat(posted.replace("Z", "+00:00")) + timedelta(hours=7)).date().isoformat(),
                           salary=f"{lo or ''}-{hi or ''} VND".strip("-") if lo or hi else "", raw=j))
        if page >= d["totalPage"]:
            break
    return out


def base(url, name):
    """Base E-hiring (VIB, ACB, ABBank...): danh sách tin nhúng sẵn trong trang, ở biến JavaScript Client.pageData.
    url = trang danh sách tất cả việc làm; phân trang ?page=N (trang không phân trang thì trả lại cùng danh sách → dừng)."""
    out, seen = [], set()
    for page in range(1, 60):
        h = get(f"{url}?page={page}")
        blobs = (json.JSONDecoder().raw_decode(h, m.end() - 1)[0] for m in re.finditer(r"Client\.pageData=\{", h))
        new = [o for o in next((b["openings"] for b in blobs if b.get("openings")), []) if o["id"] not in seen]
        if not new:
            break
        for o in new:
            seen.add(o["id"])
            # ACB: "Hội sở (Tp. HCM)<span…>;</span> Experience" → nơi làm lẫn với nhóm tin → chỉ giữ phần là địa danh
            parts = [p.strip() for p in re.sub(r"<[^>]+>", "", o.get("multi_locations") or o.get("location") or "").split(";")]
            loc = ", ".join(p for p in parts if VN_RE.search(p)) or parts[0]
            out.append(job(o["name"], name, loc, "VN", o.get("url") or o["link"],
                           COMPANY_SOURCE, day(o.get("since")), desc=o.get("content"), raw=o))
    return out


def talentnetwork(base, name):
    """Nền tảng TalentNetwork (SHB, PVcomBank, PGBank...): <base>/tim-viec-lam/vi?page=N. Mỗi công ty một giao diện riêng
    nên nhận tin qua link tiêu đề dạng /viec-lam/<tên>.<mã>.html. Không có ngày đăng → ngày thấy lần đầu."""
    out, seen = [], set()
    for page in range(1, 30):
        added = 0
        for a in soup(f"{base}/tim-viec-lam/vi?page={page}").select("a[title]"):
            url = urllib.parse.urljoin(base, a["href"])
            if url in seen or not re.search(r"/viec-lam/[^/]+\.[0-9a-f]+\.html$", url):
                continue
            seen.add(url)
            added += 1
            card = a.find_parent(class_=["panel-opening-job", "item"]) or a.parent
            loc = text(card, ".area") or next(
                (li.get_text(" ", strip=True).split(":", 1)[-1].strip() for li in card.select("li") if "Nơi làm việc" in li.get_text()), "")
            out.append(job(a["title"], name, loc, "VN", url, COMPANY_SOURCE, TODAY, raw=card))
        if not added:  # hết trang (trang vượt quá có thể trả lại trang cuối)
            break
    return out


# Thêm công ty = thêm một dòng (hệ thống, mã công ty hoặc địa chỉ trang tuyển dụng, tên hiển thị).
# Mã công ty nằm trong link ứng tuyển trên trang tuyển dụng của họ:
#   job-boards.greenhouse.io/<mã>   jobs.lever.co/<mã>   jobs.ashbyhq.com/<mã>   jobs.smartrecruiters.com/<mã>
#   <mã>.wd<N>.myworkdayjobs.com/<trang> → "<mã>.wd<N>/<trang>" (bỏ phần en-US/ nếu có)
# Trang SuccessFactors có <địa chỉ>/services/rss/job/; trang TalentNetwork có ảnh từ image.talentnetwork.vn;
# trang Ainavi có ảnh từ centralize-api.ainavi.com.vn; trang Base E-hiring có "Client.pageData=" trong mã nguồn.
COMPANIES = [
    # ngân hàng, chứng khoán
    (successfactors, "https://tuyendung.vpbank.com.vn", "VPBank"),
    (successfactors, "https://www.techcombankjobs.com", "Techcombank"),
    (successfactors, "https://tuyendung.vietcombank.com.vn", "Vietcombank"),
    (successfactors, "https://sacombankcareer.com", "Sacombank"),
    (base, "https://careers.vib.com.vn/careers", "VIB"),
    (base, "https://www.acbjobs.com.vn/alljobs", "ACB"),
    (base, "https://careers.abbank.vn/jobs", "ABBANK"),
    (ainavi, "tuyendung.tpb.vn", "TPBank"),
    (ainavi, "tuyendung.ocb.com.vn", "OCB"),
    (ainavi, "tuyendung.lpbank.com.vn", "LPBank"),
    (ainavi, "tuyendung.namabank.com.vn", "Nam A Bank"),
    (ainavi, "tuyendung.ncb-bank.vn", "NCB"),
    (ainavi, "tuyendung.vietabank.com.vn", "VietABank"),
    (talentnetwork, "https://tuyendung.shb.com.vn", "SHB"),
    (talentnetwork, "https://tuyendung.pvcombank.com.vn", "PVcomBank"),
    (talentnetwork, "https://tuyendung.pgbank.com.vn", "PGBank"),
    (talentnetwork, "https://vndirectcareers.com", "VNDIRECT"),
    # công ty khác
    (smartrecruiters, "Grab", "Grab"),
    (smartrecruiters, "BoschGroup", "Bosch Vietnam"),
    (smartrecruiters, "Gameloft", "Gameloft"),
    (smartrecruiters, "Ubisoft2", "Ubisoft"),
    (greenhouse, "axon", "Axon"),
    (greenhouse, "thoughtworks", "Thoughtworks"),
    (greenhouse, "agoda", "Agoda"),
    (lever, "ninjavan", "Ninja Van"),
    (ashby, "skymavis", "Sky Mavis"),
    (ashby, "airwallex", "Airwallex"),
    (workday, "nvidia.wd5/NVIDIAExternalCareerSite", "NVIDIA"),
    (workday, "intel.wd1/External", "Intel"),
    (workday, "marvell.wd1/MarvellCareers", "Marvell"),
    (workday, "mastercard.wd1/CorporateCareers", "Mastercard"),
    (workday, "nab.wd3/nab_careers", "NAB Innovation Centre Vietnam"),
    (workday, "manulife.wd3/MFCJH_Jobs", "Manulife"),
    (workday, "aia.wd3/External", "AIA Vietnam"),
    (workday, "prudential.wd3/prudential", "Prudential Vietnam"),
    (workday, "pwc.wd3/Global_Experienced_Careers", "PwC"),
    (workday, "unilever.wd3/Unilever_Experienced_Professionals", "Unilever"),
    (workday, "pg.wd5/1000", "P&G"),
    (workday, "abbott.wd5/abbottcareers", "Abbott"),
]


FAILED_COMPANIES = []  # main() đưa vào danh sách nguồn cần kiểm tra


def companies():
    out = []
    for fetch, slug, name in COMPANIES:
        try:
            out += fetch(slug, name)
        except Exception as e:  # một công ty đổi hệ thống tuyển dụng không làm mất các công ty khác
            print(f"  {name}: LỖI {e!r}")
            FAILED_COMPANIES.append(name)
    return out


# ---------- Trang tuyển dụng công ty tự làm: mỗi trang một hàm, trang đổi giao diện thì sửa hàm cùng tên ----------
# Các trang này không ghi ngày đăng → dùng ngày thấy tin lần đầu.

def next_data(url):
    """Trang Next.js nhúng sẵn dữ liệu trong <script id="__NEXT_DATA__"> → đọc JSON, không cần chạy trình duyệt."""
    return json.loads(soup(url).select_one("script#__NEXT_DATA__").string)["props"]["pageProps"]


def vng():
    out = []
    for page in range(1, 31):
        d = next_data(f"https://career.vng.com.vn/tim-kiem-viec-lam?page={page}")  # 10 tin/trang
        out += [job(j["title"], "VNG", j["location"], "VN", f"https://career.vng.com.vn/tim-kiem-viec-lam/chi-tiet/{j['slug']}",
                    COMPANY_SOURCE, TODAY, desc=j.get("summary"), raw=j) for j in d["jobs"]]
        if page >= d["pages"]:
            break
    return out


def momo():
    """Ô tìm kiếm của momo.careers chạy phía server (?title=), còn phân trang thì chạy bằng JS.
    ponytail: mỗi từ khóa chỉ lấy trang đầu (12 tin); MoMo tuyển >12 vị trí khớp một từ khóa thì thêm từ khóa hẹp hơn."""
    out = []
    for q in ("data", "machine learning", "AI Engineer", "Business Intelligence", "analytics", "analyst"):
        d = next_data(f"https://momo.careers/jobs-opening?title={urllib.parse.quote(q)}")
        out += [job(j["jobTitle"], "MoMo", j["location"], "VN", f"https://momo.careers/jobs/{j['subdirectory']}", COMPANY_SOURCE, TODAY, raw=j)
                for j in d["dataListJobsWithFilter"]["Items"] or []]
    return out


def be():
    out = []
    for c in soup("https://be.com.vn/tuyen-dung/").select("article"):
        if a := c.select_one("h3 a"):
            place = text(c, "p span").split("|")[0].strip()  # "Head Office | Full Time | Technology"
            out.append(job(a.get_text(strip=True), "Be Group", place, "VN", urllib.parse.urljoin("https://be.com.vn", a["href"]),
                           COMPANY_SOURCE, TODAY, raw=c))
    return out


def vnpt():
    out, seen = [], set()
    for page in range(1, 15):
        added = 0
        for c in soup("https://tuyendung.vnpt.vn/viec-lam/tat-ca-viec-lam" + (f"/p{page}" if page > 1 else "") + ".html").select(".result-item"):
            a = c.select_one("a[title]")
            if a["href"] in seen:
                continue
            seen.add(a["href"])
            added += 1
            unit = text(c, ".div-department") or "VNPT"  # đơn vị tuyển: "Công ty VNPT AI", "Tổng công ty Hạ tầng mạng"
            out.append(job(a["title"], unit if "VNPT" in unit else f"{unit} (VNPT)", text(c, ".div-location"), "VN", a["href"], COMPANY_SOURCE, TODAY, raw=c))
        if not added:  # hết trang
            break
    return out


def nashtech():
    """API mà trang jobs-finder tự gọi (POST, không cần tham số). Tin ở nhiều nước → chỉ giữ Việt Nam."""
    out = []
    for j in get_json("https://careers.nashtechglobal.com/wp-json/ntc/job/get/v2", {}):
        tax = lambda kind: [t["name"] for t in j.get("taxonomy") or [] if t["taxonomy"] == kind]
        loc = ", ".join(tax("location"))
        if "vietnam" in loc.lower():
            out.append(job(j["post_title"], "NashTech", loc.replace(" - Vietnam", ""), "VN", j["post_permalink"], COMPANY_SOURCE,
                           j["post_date"][:10], tags=tax("competency"), raw=j))
    return out


# ngân hàng, chứng khoán, ví điện tử

def dmy(s):
    """Ngày dạng '06/10/2026' đầu tiên trong chuỗi → '2026-10-06'; không có thì ngày thấy lần đầu."""
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    return f"{m[3]}-{int(m[2]):02}-{int(m[1]):02}" if m else TODAY


def paged(url, card, link, max_pages=30):
    """Đọc url.format(trang) cho tới khi trang không còn tin mới (trang vượt quá có thể trả lại trang cuối) → (thẻ tin, link, địa chỉ)."""
    seen = set()
    for page in range(1, max_pages + 1):
        added = 0
        for c in soup(url.format(page)).select(card):
            a = c.select_one(link)
            if a and (href := urllib.parse.urljoin(url, a["href"])) not in seen:
                seen.add(href)
                added += 1
                yield c, a, href
        if not added:
            break


def seabank():
    """Danh sách chỉ có tên vị trí."""
    return [job(a.get_text(strip=True), "SeABank", "", "VN", url, COMPANY_SOURCE, TODAY, raw=c)
            for c, a, url in paged("https://tuyendung.seabank.com.vn/jobs?page={}", "div[title]", "a")]


def msb():
    """Trang chỉ hiện 10 tin mới nhất (phần còn lại tải bằng JavaScript), cộng 5 kết quả tìm "data".
    Chạy 6 tiếng/lần và tin cũ được giữ lại nên vẫn không sót tin mới."""
    out = {}
    for url in ("https://jobs.msb.com.vn/latest-jobs", "https://jobs.msb.com.vn/jobs/search?keywords=data"):
        for c in soup(url).select(".job_list_row"):
            a = c.select_one("a.job_link")
            posted = text(c, ".job_post_date .jlr_value")  # "21 giờ trước" / "Oct 06, 2026"
            m = re.search(r"[A-Z][a-z]{2} \d\d, \d{4}", posted)
            out[a["href"]] = job(a.get_text(strip=True), "MSB", text(c, "a.location").lstrip("🔍 "), "VN", a["href"], COMPANY_SOURCE,
                                 datetime.strptime(m[0], "%b %d, %Y").date().isoformat() if m else ago(posted), raw=c)
    return list(out.values())


def ssi():
    return [job(a.get_text(strip=True), "SSI", text(c, ".info p"), "VN", url, COMPANY_SOURCE, dmy(c.get_text(" ").split("Đã đăng")[-1]), raw=c)
            for c, a, url in paged("https://tuyendung.ssi.com.vn/tin-tuyen-dung?page={}", ".single-content", "a.content-name")]


def tcbs():
    """Tin tuyển dụng là bài viết WordPress; trang tuyển dụng hiện 40 bài mới nhất."""
    out = {}
    for li in soup("https://www.tcbs.com.vn/ve-chung-toi/tuyen-dung/").select("li:has(> a.wp-block-latest-posts__post-title)"):
        a, t = li.select_one("a"), li.select_one("time")
        out[a["href"]] = job(a.get_text(strip=True), "TCBS", "", "VN", a["href"], COMPANY_SOURCE, day(t["datetime"] if t else ""),
                             desc=str(li.select_one(".wp-block-latest-posts__post-excerpt") or ""), raw=li)
    return list(out.values())


def vnpay():
    out = []
    for c, a, url in paged("https://tuyendung.vnpay.vn/co-hoi-nghe-nghiep?page={}", ".recruitment-item", "a.title"):
        info = [li.get_text(strip=True) for li in c.select("li")]  # [ngành, nơi làm, hạn nộp, "New"]; không có ngày đăng
        out.append(job(a.get_text(strip=True), "VNPAY", info[1] if len(info) > 1 else "", "VN", url, COMPANY_SOURCE, TODAY, raw=c))
    return out


SOURCES = [vietnamworks, careerviet, linkedin, ybox, topdev, glints, companies, vng, momo, be, vnpt, nashtech, seabank, msb, ssi, tcbs, vnpay]


# ---------- Logo ----------
LOGOS = Path(__file__).parent / "logos"


def add_logos(jobs, known=()):
    """Tin chưa có logo (trang tuyển dụng của công ty không kèm logo): dùng file logos/<tên công ty không dấu>.png;
    tên file cũng có thể là một cụm trong tên công ty (logos/vnpt.png dùng cho "Công ty VNPT AI").
    Không có file thì mượn logo của tin khác cùng tên công ty, kể cả ở file json kia (known)."""
    stems = sorted((f.stem for f in LOGOS.glob("*.png")), key=len, reverse=True)  # cụm dài khớp trước
    by_company = {j["company"].lower(): j["logo"] for j in [*known, *jobs] if j.get("logo") and j.get("company")}
    for j in jobs:
        if j.get("logo") or not j.get("company"):
            continue
        slug = slugify(j["company"])
        stem = next((f for f in stems if re.search(rf"(?:^|-){re.escape(f)}(?:-|$)", slug)), None)
        if logo := (stem and f"logos/{stem}.png") or by_company.get(j["company"].lower()):
            j["logo"] = logo
    return jobs


def merge(old, new, today=TODAY):
    """Gộp theo url, cập nhật nội dung mới nhưng giữ ngày thấy đầu tiên, bỏ job quá KEEP_DAYS ngày, mới nhất lên đầu.
    Job cũ không còn trên trang nguồn vẫn được giữ tới khi quá hạn → trang nguồn lỗi tạm thời không làm mất dữ liệu."""
    jobs = {j["url"]: j for j in old}
    for j in new:  # giữ trường tin mới không có (mô tả, kỹ năng đọc từ trang chi tiết)
        jobs[j["url"]] = {**jobs[j["url"]], **j, "date": jobs[j["url"]]["date"]} if j["url"] in jobs else j
    cutoff = (date.fromisoformat(today) - timedelta(days=KEEP_DAYS)).isoformat()
    return sorted((j for j in jobs.values() if j["date"] >= cutoff), key=lambda j: j["date"], reverse=True)


def load(path, key="jobs"):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get(key, [])
    except FileNotFoundError:
        return []


ARCHIVE_ONLY = ("full", "salary_raw", "raw")  # thông tin đầy đủ chỉ lưu vào kho; jobs.json giữ gọn cho trang web


def save(path, jobs, rejected=()):
    # có mục (sections) thì trang web không dùng đoạn tóm tắt desc → bỏ cho jobs.json nhẹ; kho vẫn giữ
    jobs = [{k: v for k, v in j.items() if k not in ARCHIVE_ONLY and not (k == "desc" and j.get("sections"))} for j in jobs]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "jobs": jobs, "rejected": sorted(rejected)},
                  f, ensure_ascii=False, indent=1)


# ---------- Kho lưu trữ: mọi job từng thấy, kể cả đã quá KEEP_DAYS ngày ----------
ARCHIVE = Path(__file__).parent / "archive"


def archive(jobs, name):
    """Ghi jobs vào archive/<name>-<tháng thấy lần đầu>.jsonl, mỗi dòng một job, cập nhật theo url, xếp theo url (diff git gọn).
    Job quá KEEP_DAYS ngày rời jobs.json nhưng vẫn nằm lại đây. name = "jobs" (bot GitHub) / "local" (máy) → hai bên không sửa chung file.
    python archive.py gộp kho thành SQLite."""
    ARCHIVE.mkdir(exist_ok=True)
    months = {}
    for j in jobs:
        months.setdefault(j["date"][:7], []).append(j)
    for month, js in months.items():
        path = ARCHIVE / f"{name}-{month}.jsonl"
        rows = {r["url"]: r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines())} if path.exists() else {}
        for j in js:
            rows[j["url"]] = {**rows.get(j["url"], {}), **j}
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(json.dumps(rows[u], ensure_ascii=False, sort_keys=True) + "\n" for u in sorted(rows))



def archived(name, folder=ARCHIVE):
    """Mọi dòng trong kho archive/<name>-*.jsonl."""
    return [json.loads(line) for f in sorted(Path(folder).glob(f"{name}-*.jsonl")) for line in f.read_text(encoding="utf-8").splitlines()]


def texts(o):
    """Mọi chuỗi dài (mô tả, yêu cầu...) trong dữ liệu JSON lồng nhau, bỏ id, slug, ngày."""
    if isinstance(o, str):
        return [o] if len(o) > 80 else []
    return [t for v in (o.values() if isinstance(o, dict) else o if isinstance(o, list) else []) for t in texts(v)]


def months(req):
    """experienceRequirements của JobPosting → (ít nhất, nhiều nhất) năm. {'monthsOfExperience': 36} → (3, None), 10 tháng → (0, 1)."""
    if isinstance(req, dict) and (m := int(float(req.get("monthsOfExperience") or 0))) > 0:
        return (m // 12, None) if m >= 12 else (0, 1)
    return experience(req) if isinstance(req, str) else None


def details(url):
    """Trang chi tiết tin → (mô tả HTML có tiêu đề từng mục, số năm kinh nghiệm nguồn ghi sẵn hoặc None).
    Hầu hết trang tuyển dụng nhúng JobPosting (schema.org) cho Google."""
    if m := re.match(r"https://jobs\.smartrecruiters\.com/([^/]+)/(\d+)", url):  # Grab, Bosch...: trang chạy bằng JS, đọc API
        ad = get_json(f"https://api.smartrecruiters.com/v1/companies/{m[1]}/postings/{m[2]}")["jobAd"]["sections"]
        return "".join(f"<h4>{h}</h4>{ad.get(k, {}).get('text', '')}" for k, h in (("jobDescription", "Mô tả công việc"), ("qualifications", "Yêu cầu"))), None
    m = re.match(r"https://([^/]+)/vi/jobs/(\w+)$", url)
    if m and m[1] in {slug for fetch, slug, _ in COMPANIES if fetch is ainavi}:  # TPBank, OCB...: trang chi tiết trả lỗi 500, đọc API
        d = get_json(f"https://centralize-api.ainavi.com.vn/api/recruitment/Recruitment/GetRecruitmentBySlug?Slug={m[2]}&Domain={m[1]}")
        return "".join(f"<h4>{h}</h4>{d.get(k) or ''}" for k, h in (("description", "Mô tả công việc"), ("requirement", "Yêu cầu"), ("benefit", "Quyền lợi"))), None
    page = soup(url)
    for script in page.select('script[type="application/ld+json"]'):
        try:
            d = json.loads(script.string or "", strict=False)
        except ValueError:
            continue
        for x in d if isinstance(d, list) else d.get("@graph", [d]) if isinstance(d, dict) else []:
            if isinstance(x, dict) and x.get("@type") == "JobPosting":
                field = lambda k: ", ".join(map(str, x[k])) if isinstance(x.get(k), list) else str(x.get(k) or "")
                benefits = field("jobBenefits")  # CareerViet: "Chế độ bảo hiểm, Du Lịch, ..." → mỗi ý một dòng
                benefits = benefits if "<" in benefits else "".join(f"<li>{b}</li>" for b in benefits.split(", ") if b)
                return html.unescape(field("description") + f"<h4>Mô tả công việc</h4>{field('responsibilities')}<h4>Yêu cầu</h4>{field('qualifications')}"
                                     f"<h4>Quyền lợi</h4>{benefits}<h4>Thông tin khác</h4>{field('skills')}"), months(x.get("experienceRequirements"))
    if el := page.select_one(".show-more-less-html__markup"):  # LinkedIn
        return str(el), None
    if el := page.select_one("script#__NEXT_DATA__"):  # MoMo, VNG: chỉ lấy dữ liệu của tin, bỏ menu và tin liên quan
        props = json.loads(el.string)["props"]["pageProps"]
        return "\n".join(texts([v for k, v in props.items() if re.search(r"job_?detail|job_data", k, re.I)])), None
    if "vietinbank.vn" in url:  # hai cột "Mô tả công việc", "Yêu cầu công việc"
        return "".join(str(el) for el in page.select(".left-10")), None
    return "", None  # trang không có dữ liệu chuẩn: chỉ đọc kỹ năng từ tên vị trí


DETAILS_PER_RUN = 300  # ponytail: lần chạy đầu đọc ~250 tin; sau đó chỉ tin mới. Tăng nếu log báo còn tin chưa đọc


def enrich(jobs, have_full={}):
    """Tin chưa có kỹ năng, chưa chia mục hoặc kho chưa có mô tả đầy đủ (have_full: url → mô tả đầy đủ trong kho): đọc trang chi tiết.
    Mỗi tin một lần: merge() giữ kỹ năng, mục cho các lần chạy sau, kho giữ mô tả đầy đủ (full, có mặt kể cả rỗng = đã đọc).
    Tin đọc trước khi có sections (mô tả trong kho bị ép thành một dòng) được đọc lại một lần."""
    done = lambda j: "skills" in j and "sections" in j and ("full" in j or j["url"] in have_full)
    bad, n = set(), 0  # trang chặn hoặc lỗi → bỏ qua cả trang đó lần này, lần sau thử lại
    for j in jobs:
        host = urllib.parse.urlparse(j["url"]).netloc
        if done(j) or host in bad or n >= DETAILS_PER_RUN:
            continue
        n += 1
        try:
            markup, exp = details(j["url"])
        except urllib.error.HTTPError as e:
            if e.code not in (404, 410):  # 404/410 = tin đã gỡ, các tin khác của trang vẫn đọc được
                bad.add(host)
                print(f"  chi tiết {host}: LỖI {e.code}")
                continue
            markup, exp = "", None
        except Exception as e:
            bad.add(host)
            print(f"  chi tiết {host}: LỖI {e!r}"[:200])
            continue
        rows = lines(markup)
        full = "\n".join(rows)
        if exp:  # số năm trang ghi sẵn (JobPosting) đáng tin hơn số đọc từ mô tả
            j["exp"] = exp_label(*exp)
            j["level"] = j.get("level") or levels("", "", exp[0])
        read(j, f"{j.get('full') or j.get('desc', '')}\n{full}")
        if full and not j.get("desc"):
            j["desc"] = short(" ".join(rows))
        # bản mới giữ xuống dòng; trang không còn dữ liệu thì giữ bản trong kho, không ghi đè bằng đoạn desc ngắn
        j["full"] = full or j.get("full") or have_full.get(j["url"]) or j.get("desc", "")
        j["sections"] = sections(j["full"].split("\n"))
        if "linkedin" in host:
            time.sleep(3)  # tránh 429
    left = sum(not done(j) for j in jobs)
    print(f"Đọc trang chi tiết: {n} tin" + (f", còn {left} tin để lần sau" if left else ""))


def run(sources, path):
    """Chạy các nguồn, gộp vào file json ở path, trả về tên các nguồn hỏng. local.py dùng lại cho local.json."""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    new, broken = [], []
    candidate = lambda j: is_data_job(j["title"]) or TRAINEE_RE.search(j["title"])  # chương trình MT: đọc chi tiết xong mới biết có giữ không
    for src in sources:
        try:
            raw = src()
            found = [j for j in raw if candidate(j)]
            print(f"{src.__name__}: {len(found)}/{len(raw)}")
            if not raw:  # 0 kết quả thô = trang đổi giao diện hoặc chặn
                broken.append(src.__name__)
            new += found
        except RateLimited as e:
            print(f"{src.__name__}: tạm bị chặn ({e}), bỏ qua lần này")
        except Exception as e:
            print(f"{src.__name__}: LỖI {e!r}")
            broken.append(src.__name__)
    # sửa bộ lọc / cách ghi lương thì job cũ cũng được lọc, quy đổi lại; chỉ giữ việc làm ở Việt Nam
    old = [{**j, "salary": vnd(j.get("salary"))} for j in load(path) if candidate(j) and j.get("region") == "VN"]
    old = [{k: v for k, v in j.items() if v != ""} for j in old]  # lương rỗng thì bỏ trường, như job()
    # chương trình MT đã đọc chi tiết và không cần kỹ năng data: không đọc lại mỗi lần chạy. Chỉ nhớ các tin nguồn còn đăng.
    rejected = set(load(path, "rejected")) & {j["url"] for j in new}
    jobs = merge(old, [j for j in new if j["url"] not in rejected])
    fulls = {r["url"]: r["full"] for r in archived(Path(path).stem) if "full" in r}
    enrich(jobs, fulls)
    for j in jobs:  # sửa SKILLS, EXP_RE, SECTIONS thì tin cũ cũng được đọc lại từ mô tả đầy đủ trong kho (jobs.json không lưu full)
        if "skills" in j and (full := j.get("full") or fulls.get(j["url"])):
            read(j, full)
            if "\n" in full:  # mô tả cũ bị ép thành một dòng: enrich() đọc lại trang chi tiết
                j["sections"] = sections(full.split("\n"))
    rejected |= {j["url"] for j in jobs if not keep(j) and "skills" in j}
    jobs = add_logos([j for j in jobs if keep(j)], known=load(LOGOS.parent / "jobs.json") + load(LOGOS.parent / "local.json"))
    seen = {j["url"] for j in new}
    for j in jobs:  # last_seen: lần cuối trang nguồn còn đăng tin → kho biết tin đăng bao lâu
        j["last_seen"] = TODAY if j["url"] in seen else j.get("last_seen", j["date"])
    save(path, jobs, rejected)
    archive(jobs, Path(path).stem)
    print(f"Tổng: {len(jobs)} job")
    return broken + FAILED_COMPANIES


def main():
    broken = run(SOURCES, "jobs.json")
    if broken:  # workflow báo đỏ + GitHub gửi email → biết nguồn nào cần sửa
        print(f"Nguồn cần kiểm tra: {', '.join(broken)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
