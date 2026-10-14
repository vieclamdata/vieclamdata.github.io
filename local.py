"""Nguồn phải cào bằng máy của bạn → local.json, rồi tự commit + push lên GitHub.

Vì sao không chạy trên GitHub Actions: các trang này chặn hoặc có thể chặn IP máy chủ nước ngoài (ITviec chặn máy chủ GitHub).
Máy bạn có IP Việt Nam. Không cần trình duyệt: get() của scrape.py dùng Scrapling giả lập Chrome nên qua được Cloudflare
của TopCV, JobsGo; VNPT trả sẵn danh sách trong HTML; NashTech có API.
Bot GitHub ghi jobs.json, script này ghi local.json → hai bên không bao giờ sửa chung một file, không bị xung đột khi push.

Cài một lần:  pip install -r requirements.txt
Chạy thử:     python local.py --no-push
Task Scheduler gọi `python local.py` 6 tiếng/lần (xem README).
"""
import json
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

from bs4 import BeautifulSoup

from scrape import COMPANY_SOURCE, TODAY, ago, day, get, get_json, job, next_data, run, slugify, soup, text

HERE = Path(__file__).parent
PAGES = 3  # số trang đọc ở mỗi trang tuyển dụng (tin mới nằm ở đầu)


def amount(lo, hi, cur="VND"):
    """Khoảng lương dạng số → '14000000-18000000 VND' để job() quy đổi sang triệu VNĐ."""
    return f"{lo}-{hi} {cur}" if lo and hi else f"Đến {hi} {cur}" if hi else f"Từ {lo} {cur}" if lo else ""


# ---------- cần IP Việt Nam ----------

def itviec():
    out = []
    for page in range(1, PAGES + 1):
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


def careerlink():
    out = []
    for page in range(1, PAGES + 1):
        for c in soup(f"https://www.careerlink.vn/viec-lam/k/data?page={page}").select("li.job-item"):
            a = c.select_one("a.job-link")
            company = c.select_one("a.job-company")
            img = c.select_one(".job-logo img")
            updated = c.select_one(".cl-datetime[data-datetime]")
            places = dict.fromkeys(x["title"] for x in c.select('a[href^="/tim-viec-lam-tai/"]'))
            out.append(job(a["title"], company["title"] if company else "", ", ".join(places), "VN",
                           urllib.parse.urljoin("https://www.careerlink.vn", a["href"].split("?")[0]), "CareerLink",
                           day(updated["data-datetime"]) if updated else TODAY,
                           logo=img["src"] if img else "", salary=text(c, ".job-salary"), hint=text(c, ".job-position")))
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
                           tags=[t for t in (j.get("skills_str") or "").split(", ") if t], hint=j.get("job_levels_str")))
        if page >= d["meta"]["last_page"]:
            break
    return out


def vieclam24h():
    """Next.js nhưng dữ liệu nằm ở props.initialState; link chi tiết lấy từ HTML theo id (cần mã ngành + tỉnh)."""
    out = []
    for page in range(1, PAGES + 1):
        html = get(f"https://vieclam24h.vn/tim-kiem-viec-lam-nhanh?q=data&page={page}")
        links = {m[1]: m[0] for m in re.findall(r'href="(/[^"?]+id(\d+)\.html)', html)}
        state = json.loads(BeautifulSoup(html, "html.parser").select_one("script#__NEXT_DATA__").string)
        for j in state["props"]["initialState"]["api"]["getJobList"]["data"]["items"]:
            if str(j["id"]) in links:
                e = j.get("employer_info") or {}
                out.append(job(j["title"], e.get("name", ""), "", "VN", "https://vieclam24h.vn" + links[str(j["id"])], "Vieclam24h",
                               day(str(j.get("approved_at") or "")), logo=e.get("logo") or "",
                               salary=amount(j.get("salary_min"), j.get("salary_max"))))
    return out


def glints():
    logo = "https://images.glints.com/unsafe/glints-dashboard.oss-ap-southeast-1-internal.aliyuncs.com/company-logo/"
    out = []
    for page in range(1, PAGES + 1):
        d = next_data(f"https://glints.com/vn/opportunities/jobs/explore?keyword=data&country=VN&page={page}")["initialJobs"]
        for j in d["jobsInPage"]:
            loc = j.get("location") or {}
            sal = (j.get("salaries") or [{}])[0] if j.get("shouldShowSalary") else {}
            out.append(job(j["title"], j["company"]["name"], ((loc.get("parents") or [{}])[0].get("name") or loc.get("name", "")), "VN",
                           f"https://glints.com/vn/opportunities/jobs/{slugify(j['title'])}/{j['id']}", "Glints", day(j["updatedAt"]),
                           logo=logo + j["company"]["logo"] if j["company"].get("logo") else "",
                           salary=amount(sal.get("minAmount"), sal.get("maxAmount"), sal.get("CurrencyCode") or "VND"), years=j.get("minYearsOfExperience") or 0))
        if not d.get("hasMore"):
            break
    return out


def topcv():
    out = []
    for page in range(1, PAGES + 1):
        for c in soup(f"https://www.topcv.vn/tim-viec-lam-data?page={page}").select(".job-item-search-result"):
            a = c.select_one("h3.title a")
            img = c.select_one(".avatar img")
            exp = re.search(r"(\d+) năm", text(c, ".item-tag"))  # "3 năm kinh nghiệm"
            out.append(job(a.get_text(strip=True), text(c, ".company-name"), text(c, ".city-text"), "VN", a["href"].split("?")[0],
                           "TopCV", ago(text(c, ".hidden-on-quick-view")), logo=(img.get("data-src") or img.get("src") or "") if img else "",
                           salary=text(c, ".title-salary"), years=int(exp[1]) if exp else 0))
    return out


def jobsgo():
    out = []
    for page in range(1, PAGES + 1):
        for c in soup(f"https://jobsgo.vn/viec-lam.html?q=data&page={page}").select(".job-card"):
            a = c.select_one("h3.job-title a")
            info = [s.get_text(strip=True) for s in c.select(".text-primary span") if s.get_text(strip=True) not in ("", "|")]  # [lương, nơi làm]
            img = c.select_one("img")
            out.append(job(a["title"], text(c, "a.company-title"), info[-1] if len(info) > 1 else "", "VN", a["href"].split("?")[0],
                           "JobsGo", ago(c.get_text(" ")), logo=img["src"] if img else "", salary=info[0] if info else ""))
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
            out.append(job(a["title"], text(c, ".div-department") or "VNPT", text(c, ".div-location"), "VN", a["href"], COMPANY_SOURCE, TODAY))
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
                           j["post_date"][:10], tags=tax("competency")))
    return out


LOCAL_SOURCES = [itviec, topcv, topdev, careerlink, jobsgo, vieclam24h, glints, vnpt, nashtech]


def git(*args):
    subprocess.run(["git", *args], cwd=HERE, check=True)


def main():
    push = "--no-push" not in sys.argv
    if push:
        git("pull", "--rebase", "--autostash")  # lấy bản mới (bot vừa commit jobs.json) trước khi ghi
    broken = run(LOCAL_SOURCES, str(HERE / "local.json"))
    if push:
        git("add", "local.json")
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=HERE).returncode:  # có thay đổi mới commit
            git("commit", "-m", "update local jobs")
            git("pull", "--rebase")
            git("push")
    if broken:  # Task Scheduler ghi "Last Run Result" = 0x1; chi tiết trong local.log
        print(f"Nguồn cần kiểm tra: {', '.join(broken)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
