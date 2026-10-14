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

from bs4 import BeautifulSoup
from scrapling.fetchers import Fetcher

logging.getLogger("scrapling").setLevel(logging.WARNING)  # bỏ dòng log mỗi request
TODAY = date.today().isoformat()
KEEP_DAYS = 30

# (?-i:...) = phân biệt hoa thường, để "BI"/"ML" không khớp "mobile", "html"...
DATA_RE = re.compile(
    r"\bdata\b|dữ liệu|business intelligence|analytics|machine learning|deep learning|power ?bi|tableau|"
    r"(?-i:\bBI\b|\bML\b|\bMLOps\b|\bETL\b|\bSQL\b)|(?-i:\bAI\b) (?:engineer|scientist)",
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
    r"|machine learning|business intelligence|power ?bi|tableau",
    re.I,
)

# cấp bậc → từ khóa trong tên vị trí hoặc nhãn cấp bậc của nguồn. "Junior/Fresher" khớp cả hai.
LEVELS = {
    "intern": r"\bintern(?:ship)?\b|thực tập|fresher|trainee|\bgraduate\b|mới tốt nghiệp|sinh viên|entry[- ]level",
    "junior": r"\bjunior\b|\bjr\b|\bassociate\b(?!\s+director)",  # "Associate" = nhãn junior của LinkedIn/SmartRecruiters
    "mid": r"\bmid(?:dle)?\b(?!\s*east)|intermediate|midweight",
    "senior": r"\bsenior\b|\bsr\b|cao cấp|\bexpert\b|chuyên gia",
    # "staff" chỉ tính khi là cấp kỹ sư ("Staff Data Engineer"); ở VN "BI Staff" = nhân viên.
    # "tăng trưởng" (growth) không phải "trưởng phòng"; "quản lý" chỉ tính ở đầu tên, "chuyên viên quản lý dữ liệu" là nghiệp vụ.
    "lead": r"\blead(?:er)?\b|\bhead\b|manager|director|principal|\bchief\b|\bvp\b|staff (?:\w+ ){0,3}(?:engineer|scientist|architect)"
            r"|(?<!tăng )trưởng|phó phòng|giám đốc|^quản lý",
}


def is_data_job(text):
    if not DATA_RE.search(text) or NOT_DATA_RE.search(text):
        return False
    return not OTHER_ROLE_RE.search(text) or bool(DATA_ROLE_RE.search(text))


def levels(title, hint="", years=0):
    """Tên vị trí → cấp bậc. Tên không ghi thì dùng nhãn cấp bậc của nguồn, cuối cùng là số năm kinh nghiệm."""
    for text in (title, hint or ""):
        if found := [k for k, pat in LEVELS.items() if re.search(pat, text, re.I)]:
            return found
    if years:
        return ["junior" if years <= 1 else "mid" if years < 5 else "senior"]
    return []


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


def plain(markup, n=400):
    """Mô tả HTML → đoạn văn ngắn cho khung xem nhanh."""
    t = " ".join(BeautifulSoup(markup or "", "html.parser").get_text(" ").split())
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


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
    prefix = "Đến " if re.match(r"(tới|đến|lên đến|up ?to)", low) else "Từ " if re.match(r"(từ|trên|from)", low) else ""
    return f"{prefix}{approx}{'–'.join(fmt(n) for n in nums[:2])} triệu"


def job(title, company, location, region, url, source, posted, logo="", salary="", tags=(), desc="", hint="", years=0):
    """hint: nhãn cấp bậc của nguồn ("Senior", "Trưởng phòng"...), years: số năm kinh nghiệm yêu cầu."""
    extra = dict(logo=logo, salary=vnd(salary), tags=list(tags)[:6], desc=desc, level=levels(title, hint, years))
    return dict(title=title.strip(), company=(company or "").strip(), location=(location or "").strip(),
                region=region, url=url, source=source, date=posted, **{k: v for k, v in extra.items() if v})


# ---------- Việt Nam ----------

def vietnamworks():
    out = []
    for q in ("data", "dữ liệu", "BI", "machine learning"):
        d = get_json("https://ms.vietnamworks.com/job-search/v1.0/search", {"query": q, "page": 0, "hitsPerPage": 100})
        for j in d["data"]:
            loc = ", ".join(l.get("cityNameVI") or l.get("cityName", "") for l in j.get("workingLocations") or [])
            out.append(job(j["jobTitle"], j["companyName"], loc, "VN", j["jobUrl"], "VietnamWorks", day(j["approvedOn"]),
                           logo=j.get("companyLogo") or "", salary=j.get("prettySalary"),
                           tags=[s["skillName"] for s in j.get("skills") or []], desc=plain(j.get("jobDescription")),
                           hint=j.get("jobLevelVI"), years=j.get("yearsOfExperience") or 0))
    return out


def careerviet():
    out = []
    for c in soup("https://careerviet.vn/viec-lam/data-k-vi.html").select("div.job-item"):
        a = c.select_one("a.job_link")
        m = re.search(r"Cập nhật\s*:\s*(\d\d)-(\d\d)-(\d{4})", c.get_text(" ", strip=True))
        img = c.select_one("img.image-logo-emp")
        src = img.get("src", "") if img else ""  # /_next/image?url=<ảnh gốc>&w=...
        out.append(job(a["title"], text(c, "a.company-name"), text(c, "div.location", ", "), "VN",
                       urllib.parse.urljoin("https://careerviet.vn", a["href"]), "CareerViet",
                       f"{m[3]}-{m[2]}-{m[1]}" if m else TODAY,
                       logo=urllib.parse.parse_qs(urllib.parse.urlparse(src).query).get("url", [src])[0],
                       salary=re.sub(r"^Lương:\s*", "", text(c, "div.salary"))))
    return out


class RateLimited(Exception):
    """Nguồn tạm thời chặn vì gửi quá nhiều request: không tính là hỏng (workflow không báo đỏ), tin cũ vẫn giữ, lần chạy sau thử lại."""


def linkedin():
    """API công khai của LinkedIn Jobs, không cần đăng nhập."""
    out = []
    for start in (0, 25, 50, 75):
        q = urllib.parse.urlencode({"keywords": "data", "location": "Vietnam", "sortBy": "DD", "start": start})
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
                           logo=img["data-delayed-url"] if img else "", salary=text(c, ".job-search-card__salary-info")))
        if not cards:
            break
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
                           logo=(p.get("photo") or "").replace("http://", "https://"), desc=plain(p.get("summary"))))
    return out


# ---------- Trang tuyển dụng của công ty ----------
# Nhiều công ty dùng hệ thống tuyển dụng (ATS) có API công khai → mỗi hàm dưới đây đọc được mọi công ty dùng hệ thống đó.
# Chỉ lấy tin ở Việt Nam. Danh sách công ty: COMPANIES ở cuối phần này.
COMPANY_SOURCE = "Trang công ty"
VN_RE = re.compile(r"viet ?nam|việt nam|ha ?noi|hà nội|ho chi minh|hồ chí minh|\bhcm|sai ?gon|da ?nang|đà nẵng|binh duong|bình dương"
                   r"|hai phong|hải phòng|bac ninh|bắc ninh|can tho|cần thơ", re.I)


def greenhouse(slug, name):
    return [job(j["title"], name, j["location"]["name"], "VN", j["absolute_url"], COMPANY_SOURCE,
                day(j.get("first_published") or j["updated_at"]), desc=plain(html.unescape(j.get("content") or "")))
            for j in get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")["jobs"]
            if VN_RE.search(j["location"]["name"])]


def lever(slug, name):
    return [job(j["text"], name, j["categories"].get("location", ""), "VN", j["hostedUrl"], COMPANY_SOURCE,
                day(str(j["createdAt"] // 1000)), desc=plain(j.get("descriptionPlain")))
            for j in get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
            if j.get("country") == "VN" or VN_RE.search(j["categories"].get("location", ""))]


def ashby(slug, name):
    out = []
    for j in get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")["jobs"]:
        country = ((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry", "")
        locs = [j.get("location", ""), country] + [l.get("location", "") for l in j.get("secondaryLocations") or []]
        if loc := next((l for l in locs if VN_RE.search(l)), None):
            out.append(job(j["title"], name, loc, "VN", j["jobUrl"], COMPANY_SOURCE, day(j["publishedAt"]),
                           salary=(j.get("compensation") or {}).get("compensationTierSummary"), desc=plain(j.get("descriptionPlain"))))
    return out


def smartrecruiters(slug, name):
    out = []
    for offset in range(0, 500, 100):
        d = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?country=vn&limit=100&offset={offset}")
        for j in d["content"]:
            loc = j["location"]
            out.append(job(j["name"], name, loc.get("city") or loc.get("region") or "Vietnam", "VN",
                           f"https://jobs.smartrecruiters.com/{j['company']['identifier']}/{j['id']}", COMPANY_SOURCE,
                           day(j["releasedDate"]), hint=(j.get("experienceLevel") or {}).get("label")))
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
            if not is_data_job(j.get("title", "")):  # có tin ẩn chỉ còn mã tin, không có tên
                continue
            info = get_json(api + j["externalPath"])["jobPostingInfo"]
            locs = [info.get("location", "")] + info.get("additionalLocations", [])
            if VN_RE.search((info.get("country") or {}).get("descriptor", "")) or any(VN_RE.search(l) for l in locs):
                out.append(job(info["title"], name, " / ".join(l for l in locs if VN_RE.search(l)) or locs[0], "VN", info["externalUrl"],
                               COMPANY_SOURCE, info.get("startDate") or ago(j.get("postedOn", "")), desc=plain(info.get("jobDescription"))))
        if offset + 20 >= total:
            break
    return out


def successfactors(base, name, keywords=("data", "dữ liệu", "analytics", "Business Intelligence", "AI", "machine learning")):
    """SAP SuccessFactors (VPBank, Techcombank, Vietcombank, Sacombank...) có RSS. Tiêu đề dạng 'Tên vị trí (Hà Nội, VN)'.
    ponytail: RSS trả tối đa 20 tin mới nhất mỗi từ khóa; công ty tuyển >20 vị trí data cùng lúc thì thêm từ khóa hẹp hơn."""
    out = []
    for kw in keywords:
        for it in ET.fromstring(get(f"{base}/services/rss/job/?locale=vi_VN&keywords=({urllib.parse.quote(kw)})")).iter("item"):
            m = re.match(r"(.*?)\s*\(([^()]*), VN\)\s*$", it.findtext("title"))
            title, loc = (m[1], m[2]) if m else (it.findtext("title"), "")
            pub = it.findtext("pubDate")  # có tin không ghi ngày đăng → ngày thấy lần đầu
            out.append(job(title, name, loc, "VN", it.findtext("link"), COMPANY_SOURCE,
                           parsedate_to_datetime(pub).date().isoformat() if pub else TODAY, desc=plain(it.findtext("description"))))
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
                           salary=f"{lo or ''}-{hi or ''} VND".strip("-") if lo or hi else ""))
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
                           COMPANY_SOURCE, day(o.get("since")), desc=plain(o.get("content"))))
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
            out.append(job(a["title"], name, loc, "VN", url, COMPANY_SOURCE, TODAY))
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
                    COMPANY_SOURCE, TODAY, desc=plain(j.get("summary"))) for j in d["jobs"]]
        if page >= d["pages"]:
            break
    return out


def momo():
    """Ô tìm kiếm của momo.careers chạy phía server (?title=), còn phân trang thì chạy bằng JS.
    ponytail: mỗi từ khóa chỉ lấy trang đầu (12 tin); MoMo tuyển >12 vị trí khớp một từ khóa thì thêm từ khóa hẹp hơn."""
    out = []
    for q in ("data", "machine learning", "AI Engineer", "Business Intelligence", "analytics", "analyst"):
        d = next_data(f"https://momo.careers/jobs-opening?title={urllib.parse.quote(q)}")
        out += [job(j["jobTitle"], "MoMo", j["location"], "VN", f"https://momo.careers/jobs/{j['subdirectory']}", COMPANY_SOURCE, TODAY)
                for j in d["dataListJobsWithFilter"]["Items"] or []]
    return out


def be():
    out = []
    for c in soup("https://be.com.vn/tuyen-dung/").select("article"):
        if a := c.select_one("h3 a"):
            place = text(c, "p span").split("|")[0].strip()  # "Head Office | Full Time | Technology"
            out.append(job(a.get_text(strip=True), "Be Group", place, "VN", urllib.parse.urljoin("https://be.com.vn", a["href"]),
                           COMPANY_SOURCE, TODAY))
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
    return [job(a.get_text(strip=True), "SeABank", "", "VN", url, COMPANY_SOURCE, TODAY)
            for c, a, url in paged("https://tuyendung.seabank.com.vn/jobs?page={}", "div[title]", "a")]


def vietinbank():
    """Nhiều tin tuyển cho chi nhánh: địa chỉ thường để trống → dùng tên chi nhánh/phòng ban."""
    return [job(text(c, ".c-line-jobtitle"), "VietinBank", text(c, ".c-line-address") or text(c, ".c-line-jobcontent"), "VN", url,
                COMPANY_SOURCE, dmy(c.get_text(" ").split("Ngày đăng")[-1]))
            for c, a, url in paged("https://tuyendung.vietinbank.vn/tuyendung/tuyen-dung?page={}", ".c-card", "a.btn-apply-ut", 40)]


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
                                 datetime.strptime(m[0], "%b %d, %Y").date().isoformat() if m else ago(posted))
    return list(out.values())


def ssi():
    return [job(a.get_text(strip=True), "SSI", text(c, ".info p"), "VN", url, COMPANY_SOURCE, dmy(c.get_text(" ").split("Đã đăng")[-1]))
            for c, a, url in paged("https://tuyendung.ssi.com.vn/tin-tuyen-dung?page={}", ".single-content", "a.content-name")]


def tcbs():
    """Tin tuyển dụng là bài viết WordPress; trang tuyển dụng hiện 40 bài mới nhất."""
    out = {}
    for li in soup("https://www.tcbs.com.vn/ve-chung-toi/tuyen-dung/").select("li:has(> a.wp-block-latest-posts__post-title)"):
        a, t = li.select_one("a"), li.select_one("time")
        out[a["href"]] = job(a.get_text(strip=True), "TCBS", "", "VN", a["href"], COMPANY_SOURCE, day(t["datetime"] if t else ""),
                             desc=plain(str(li.select_one(".wp-block-latest-posts__post-excerpt") or "")))
    return list(out.values())


def vnpay():
    out = []
    for c, a, url in paged("https://tuyendung.vnpay.vn/co-hoi-nghe-nghiep?page={}", ".recruitment-item", "a.title"):
        info = [li.get_text(strip=True) for li in c.select("li")]  # [ngành, nơi làm, hạn nộp, "New"]; không có ngày đăng
        out.append(job(a.get_text(strip=True), "VNPAY", info[1] if len(info) > 1 else "", "VN", url, COMPANY_SOURCE, TODAY))
    return out


SOURCES = [vietnamworks, careerviet, linkedin, ybox, companies, vng, momo, be, seabank, vietinbank, msb, ssi, tcbs, vnpay]


def merge(old, new, today=TODAY):
    """Gộp theo url, cập nhật nội dung mới nhưng giữ ngày thấy đầu tiên, bỏ job quá KEEP_DAYS ngày, mới nhất lên đầu.
    Job cũ không còn trên trang nguồn vẫn được giữ tới khi quá hạn → trang nguồn lỗi tạm thời không làm mất dữ liệu."""
    jobs = {j["url"]: j for j in old}
    for j in new:
        jobs[j["url"]] = {**j, "date": jobs[j["url"]]["date"]} if j["url"] in jobs else j
    cutoff = (date.fromisoformat(today) - timedelta(days=KEEP_DAYS)).isoformat()
    return sorted((j for j in jobs.values() if j["date"] >= cutoff), key=lambda j: j["date"], reverse=True)


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)["jobs"]
    except FileNotFoundError:
        return []


def save(path, jobs):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "jobs": jobs}, f, ensure_ascii=False, indent=1)


def run(sources, path):
    """Chạy các nguồn, gộp vào file json ở path, trả về tên các nguồn hỏng. local.py dùng lại cho local.json."""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    new, broken = [], []
    for src in sources:
        try:
            raw = src()
            found = [j for j in raw if is_data_job(j["title"])]
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
    old = [{**j, "salary": vnd(j.get("salary"))} for j in load(path) if is_data_job(j["title"]) and j.get("region") == "VN"]
    old = [{k: v for k, v in j.items() if v != ""} for j in old]  # lương rỗng thì bỏ trường, như job()
    jobs = merge(old, new)
    save(path, jobs)
    print(f"Tổng: {len(jobs)} job")
    return broken + FAILED_COMPANIES


def main():
    broken = run(SOURCES, "jobs.json")
    if broken:  # workflow báo đỏ + GitHub gửi email → biết nguồn nào cần sửa
        print(f"Nguồn cần kiểm tra: {', '.join(broken)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
