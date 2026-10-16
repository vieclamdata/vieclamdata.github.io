"""Nguồn phải cào bằng máy của bạn → local.json, rồi tự commit + push lên GitHub.

Vì sao không chạy trên GitHub Actions: đã thử (10/2026), ITviec, TopCV, JobsGo, Vieclam24h trả 403, VietinBank trả 502 với máy chủ GitHub,
CareerLink trả trang rỗng. Máy bạn có IP Việt Nam. Không cần trình duyệt: get() của scrape.py dùng Scrapling giả lập Chrome
nên qua được Cloudflare của TopCV, JobsGo.
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

from scrape import COMPANY_SOURCE, PAGES, TODAY, ago, amount, day, dmy, get, job, paged, run, soup, text

HERE = Path(__file__).parent


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
                           tags=[t.get_text(strip=True) for t in c.select("a.itag")], raw=c))
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
                           logo=img["src"] if img else "", salary=text(c, ".job-salary"), hint=text(c, ".job-position"), raw=c))
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
                               salary=amount(j.get("salary_min"), j.get("salary_max")), raw=j))
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
                           salary=text(c, ".title-salary"), years=int(exp[1]) if exp else 0, raw=c))
    return out


def jobsgo():
    out = []
    for page in range(1, PAGES + 1):
        for c in soup(f"https://jobsgo.vn/viec-lam.html?q=data&page={page}").select(".job-card"):
            a = c.select_one("h3.job-title a")
            info = [s.get_text(strip=True) for s in c.select(".text-primary span") if s.get_text(strip=True) not in ("", "|")]  # [lương, nơi làm]
            img = c.select_one("img")
            out.append(job(a["title"], text(c, "a.company-title"), info[-1] if len(info) > 1 else "", "VN", a["href"].split("?")[0],
                           "JobsGo", ago(c.get_text(" ")), logo=img["src"] if img else "", salary=info[0] if info else "", raw=c))
    return out


def vietinbank():
    """Trả 502 với máy chủ GitHub (10/2026). Nhiều tin tuyển cho chi nhánh: địa chỉ thường để trống → dùng tên chi nhánh/phòng ban."""
    return [job(text(c, ".c-line-jobtitle"), "VietinBank", text(c, ".c-line-address") or text(c, ".c-line-jobcontent"), "VN", url,
                COMPANY_SOURCE, dmy(c.get_text(" ").split("Ngày đăng")[-1]), raw=c)
            for c, a, url in paged("https://tuyendung.vietinbank.vn/tuyen-dung?page={}", ".c-card", "a.btn-apply-ut", 40)]


LOCAL_SOURCES = [itviec, topcv, careerlink, jobsgo, vieclam24h, vietinbank]


def git(*args):
    subprocess.run(["git", *args], cwd=HERE, check=True)


def main():
    push = "--no-push" not in sys.argv
    if push:
        git("pull", "--rebase", "--autostash")  # lấy bản mới (bot vừa commit jobs.json) trước khi ghi
    broken = run(LOCAL_SOURCES, str(HERE / "local.json"))
    if push:
        git("add", "local.json", "archive/local-*.jsonl")  # chỉ kho của local.py; archive/jobs-* là của bot
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=HERE).returncode:  # có thay đổi mới commit
            git("commit", "-m", "update local jobs")
            git("pull", "--rebase")
            git("push")
    if broken:  # Task Scheduler ghi "Last Run Result" = 0x1; chi tiết trong local.log
        print(f"Nguồn cần kiểm tra: {', '.join(broken)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
