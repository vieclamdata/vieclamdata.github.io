"""Thu thập việc làm ngành data từ các trang tuyển dụng → jobs.json.

Chạy: python scrape.py   (GitHub Actions tự chạy 6 tiếng/lần)
"""
import html
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
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
    r"data entry|nhập liệu|data (?:\w+ ){0,2}(?:có )?sẵn|data nóng|spam data|data cent(?:er|re)|data[- ]driven|annotat|gán nhãn"
    r"|telesales|telemarketing|quản trị cơ sở dữ liệu|\bDBA\b|database administrat|sql server administrat",
    re.I,
)
# vị trí thuộc nghề khác (sales, HR, pháp chế, hành chính, hỗ trợ) chỉ nhắc tới data/analytics → loại,
# trừ khi tên vị trí là vai trò data rõ ràng ("Sales Data Analyst", "HR Data Analyst" vẫn giữ)
OTHER_ROLE_RE = re.compile(
    r"\bsales\b|account (?:executive|manager)|business development|nhân viên kinh doanh|chuyên viên kinh doanh|bán hàng"
    r"|recruit|talent acquisition|tuyển sinh|nhân sự|nguồn nhân lực|\bHR\b|counsel|pháp chế|compensation|hành chính"
    r"|customer (?:service|support|success)|chăm sóc khách hàng|application support",
    re.I,
)
DATA_ROLE_RE = re.compile(
    r"data (?:analyst|engineer|scientist|architect|science|analytics|modeler)|phân tích dữ liệu|kỹ sư dữ liệu|khoa học dữ liệu"
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
    # header giống trình duyệt thật; thiếu Accept/Accept-Language thì Cloudflare (ITviec) dễ chặn IP máy chủ GitHub
    headers = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
               "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8"}
    if body is not None:
        body = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


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
    """'Posted 3 days ago' → ngày đăng."""
    m = re.search(r"(\d+)\s*(minute|hour|day|week|month)", s)
    if not m:
        return TODAY
    days = int(m[1]) * {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30}[m[2]]
    return (date.today() - timedelta(days=days)).isoformat()


def plain(markup, n=400):
    """Mô tả HTML → đoạn văn ngắn cho khung xem nhanh."""
    t = " ".join(BeautifulSoup(markup or "", "html.parser").get_text(" ").split())
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


def money(lo, hi, cur="USD", per="năm"):
    """(60000, 90000) → '$60k–90k/năm'. API trả số hoặc chuỗi, thiếu thì None/0."""
    k = lambda v: f"{round(v / 1000)}k" if v >= 1000 else f"{v:g}"
    rng = "–".join(dict.fromkeys(k(float(v)) for v in (lo, hi) if v))
    sym = {"USD": "$", "EUR": "€", "GBP": "£"}.get(cur or "USD", f"{cur} ")
    return f"{sym}{rng}/{per}" if rng else ""


def job(title, company, location, region, url, source, posted, logo="", salary="", tags=(), desc="", hint="", years=0):
    """hint: nhãn cấp bậc của nguồn ("Senior", "Trưởng phòng"...), years: số năm kinh nghiệm yêu cầu."""
    extra = dict(logo=logo, salary=(salary or "").strip(), tags=list(tags)[:6], desc=desc, level=levels(title, hint, years))
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


def itviec():
    out = []
    for page in (1, 2, 3):
        for c in soup(f"https://itviec.com/it-jobs/data?page={page}").select("div.job-card"):
            a = c.select_one("h3 a")
            loc = c.select_one("div.text-rich-grey[title]")
            img = c.select_one("img[data-src]")
            sal = text(c, "div.salary")  # khách chưa đăng nhập chỉ thấy "Sign in to view salary"
            out.append(job(a.get_text(strip=True), text(c, 'a.text-rich-grey[href^="/companies"]'),
                           loc["title"] if loc else "", "VN", a["href"].split("?")[0], "ITviec", ago(c.get_text(" ")),
                           logo=img["data-src"] if img else "", salary="" if "sign in" in sal.lower() else sal,
                           tags=[t.get_text(strip=True) for t in c.select("a.itag")]))
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


def linkedin():
    """API công khai của LinkedIn Jobs, không cần đăng nhập."""
    out = []
    for location, region, extra in (("Vietnam", "VN", {}), ("Worldwide", "Remote", {"f_WT": 2})):
        for start in (0, 25, 50, 75):
            q = urllib.parse.urlencode({"keywords": "data", "location": location, "sortBy": "DD", "start": start, **extra})
            try:
                cards = soup(f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?{q}").select("div.base-search-card")
            except urllib.error.HTTPError as e:
                if e.code != 429 or not out:
                    raise
                break  # bị giới hạn tốc độ giữa chừng → giữ các trang đã lấy được
            for c in cards:
                job_id = c.get("data-entity-urn", "").rsplit(":", 1)[-1]
                t = c.select_one("time")
                img = c.select_one("img[data-delayed-url]")
                out.append(job(text(c, "h3"), text(c, "h4"), text(c, ".job-search-card__location"), region,
                               f"https://www.linkedin.com/jobs/view/{job_id}", "LinkedIn", t["datetime"] if t else TODAY,
                               logo=img["data-delayed-url"] if img else "", salary=text(c, ".job-search-card__salary-info")))
            if not cards:
                break
            time.sleep(5)  # tránh bị LinkedIn chặn (429)
    return out


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
            slug = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFD", p["title"].replace("đ", "d").replace("Đ", "D"))
                          .encode("ascii", "ignore").decode().lower()).strip("-")
            out.append(job(title, company, loc, "VN", f"https://ybox.vn/tuyen-dung/{slug}-{p['_id']}", "Ybox", day(p["publishedAt"]),
                           logo=(p.get("photo") or "").replace("http://", "https://"), desc=plain(p.get("summary"))))
    return out


# ---------- Remote quốc tế ----------

def remoteok():
    return [job(j["position"], j["company"], j.get("location") or "Remote", "Remote", j["url"], "RemoteOK", day(j["date"]),
                logo=j.get("logo") or j.get("company_logo") or "", salary=money(j.get("salary_min"), j.get("salary_max")),
                desc=plain(j.get("description")))
            for j in get_json("https://remoteok.com/api")[1:]]  # phần tử đầu là thông báo pháp lý


def remotive():
    # Remotive yêu cầu tối đa 4 lần gọi/ngày → khớp lịch 6 tiếng/lần
    return [job(j["title"], j["company_name"], j["candidate_required_location"], "Remote", j["url"], "Remotive", day(j["publication_date"]),
                logo=j.get("company_logo") or "", salary=j.get("salary"), tags=j.get("tags") or [], desc=plain(j.get("description")))
            for j in get_json("https://remotive.com/api/remote-jobs?category=data")["jobs"]]


def arbeitnow():
    return [job(j["title"], j["company_name"], j["location"], "Remote", j["url"], "Arbeitnow", day(j["created_at"]),
                desc=plain(j.get("description")))
            for j in get_json("https://www.arbeitnow.com/api/job-board-api")["data"] if j["remote"]]


def himalayas():
    per = {"monthly": "tháng", "month": "tháng", "hourly": "giờ", "hour": "giờ"}
    return [job(j["title"], j["companyName"], ", ".join(j.get("locationRestrictions") or []) or "Worldwide", "Remote",
                j["guid"], "Himalayas", day(j["pubDate"]), logo=j.get("companyLogo") or "",
                salary=money(j.get("minSalary"), j.get("maxSalary"), j.get("currency"), per.get(j.get("salaryPeriod"), "năm")),
                desc=plain(j.get("description")), hint=" ".join(j.get("seniority") or []))
            for j in get_json("https://himalayas.app/jobs/api/search?q=data")["jobs"]]


def jobicy():
    return [job(j["jobTitle"], j["companyName"], j.get("jobGeo", ""), "Remote", j["url"], "Jobicy", day(j["pubDate"]),
                logo=j.get("companyLogo") or "", salary=money(j.get("annualSalaryMin"), j.get("annualSalaryMax"), j.get("salaryCurrency")),
                desc=plain(j.get("jobDescription")), hint=j.get("jobLevel"))
            for j in get_json("https://jobicy.com/api/v2/remote-jobs?count=100&tag=data")["jobs"]]


# ---------- Trang tuyển dụng của công ty ----------
# Nhiều công ty dùng hệ thống tuyển dụng (ATS) có API công khai → mỗi hàm dưới đây đọc được mọi công ty dùng hệ thống đó.
# Chỉ lấy tin ở Việt Nam. Danh sách công ty: COMPANIES ở cuối phần này.
COMPANY_SOURCE = "Trang công ty"
VN_RE = re.compile(r"viet ?nam|ha ?noi|hà nội|ho chi minh|hồ chí minh|hcmc|sai ?gon|da ?nang|đà nẵng", re.I)


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


def successfactors(base, name, keywords=("data", "dữ liệu", "Business Intelligence", "AI", "machine learning")):
    """SAP SuccessFactors (VPBank...) có RSS. Tiêu đề dạng 'Tên vị trí (Hà Nội, VN)'.
    ponytail: RSS trả tối đa 20 tin mới nhất mỗi từ khóa; công ty tuyển >20 vị trí data cùng lúc thì thêm từ khóa hẹp hơn."""
    out = []
    for kw in keywords:
        for it in ET.fromstring(get(f"{base}/services/rss/job/?locale=vi_VN&keywords=({urllib.parse.quote(kw)})")).iter("item"):
            m = re.match(r"(.*?)\s*\(([^()]*), VN\)\s*$", it.findtext("title"))
            title, loc = (m[1], m[2]) if m else (it.findtext("title"), "")
            out.append(job(title, name, loc, "VN", it.findtext("link"), COMPANY_SOURCE,
                           parsedate_to_datetime(it.findtext("pubDate")).date().isoformat(), desc=plain(it.findtext("description"))))
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
# Trang SuccessFactors có <địa chỉ>/services/rss/job/; trang TalentNetwork có ảnh từ image.talentnetwork.vn.
COMPANIES = [
    (successfactors, "https://tuyendung.vpbank.com.vn", "VPBank"),
    (talentnetwork, "https://tuyendung.shb.com.vn", "SHB"),
    (talentnetwork, "https://tuyendung.pvcombank.com.vn", "PVcomBank"),
    (talentnetwork, "https://tuyendung.pgbank.com.vn", "PGBank"),
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


SOURCES = [vietnamworks, itviec, careerviet, linkedin, ybox, remoteok, remotive, arbeitnow, himalayas, jobicy, companies, vng, momo, be]


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


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    new, broken = [], []
    for src in SOURCES:
        try:
            raw = src()
            found = [j for j in raw if is_data_job(j["title"])]
            print(f"{src.__name__}: {len(found)}/{len(raw)}")
            if not raw:  # 0 kết quả thô = trang đổi giao diện hoặc chặn
                broken.append(src.__name__)
            new += found
        except Exception as e:
            print(f"{src.__name__}: LỖI {e!r}")
            broken.append(src.__name__)
    old = [j for j in load("jobs.json") if is_data_job(j["title"])]  # sửa bộ lọc thì job cũ cũng được lọc lại
    jobs = merge(old, new)
    save("jobs.json", jobs)
    print(f"Tổng: {len(jobs)} job")
    broken += FAILED_COMPANIES
    if broken:  # workflow báo đỏ + GitHub gửi email → biết nguồn nào cần sửa
        print(f"Nguồn cần kiểm tra: {', '.join(broken)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
