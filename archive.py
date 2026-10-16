"""Gộp kho archive/*.jsonl (mọi job từng thấy, kể cả đã quá 30 ngày) thành archive.db (SQLite).

Chạy:  python archive.py   → archive.db, mở bằng DB Browser for SQLite, DBeaver, Python, Excel (qua ODBC)...
archive.db không commit: tạo lại từ kho lúc nào cũng được. Kho do scrape.py (bot) và local.py ghi mỗi lần chạy.

Bảng jobs: một dòng một tin. date = ngày thấy lần đầu, last_seen = lần cuối trang nguồn còn đăng
(trống = chưa biết: tin đã gỡ trước khi có kho, lấy lại từ lịch sử git). salary_min / salary_max: triệu VNĐ/tháng, trống = không giới hạn hoặc không ghi.
description = đoạn ngắn hiện trên web; full = mô tả đầy đủ (mô tả, yêu cầu, quyền lợi); salary_raw = lương ghi nguyên văn;
raw = bản ghi gốc của nguồn: JSON (dùng json_extract(raw, '$.tên_trường')) hoặc chữ trên thẻ tin với trang HTML.
Tin cào trước khi có full/raw: trống tới khi bot đọc lại trang chi tiết (tin còn đăng) hoặc mãi trống (tin đã gỡ).
Bảng job_skills: (url, skill), mỗi kỹ năng của tin một dòng.
"""
import json
import re
import sqlite3
from pathlib import Path

HERE = Path(__file__).parent
COLUMNS = ["url", "title", "company", "location", "region", "source", "date", "last_seen",
           "salary", "salary_min", "salary_max", "salary_raw", "level", "tags", "skills", "description", "full", "raw", "logo"]


def salary_range(s):
    """'≈18–31 triệu' → (18, 31), 'Đến 30 triệu' → (None, 30), 'Từ 20 triệu' → (20, None), 'Thỏa thuận' → (None, None)."""
    n = [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:,\d+)?", s or "")]
    if not n:
        return None, None
    if s.startswith("Đến"):
        return None, n[0]
    if s.startswith("Từ"):
        return n[0], None
    return n[0], n[1] if len(n) > 1 else n[0]


def main():
    jobs = {}  # cùng tin có ở cả kho bot lẫn kho máy (nguồn đã chuyển chỗ) → giữ bản thấy gần nhất
    for f in sorted((HERE / "archive").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            j = json.loads(line)
            if j["url"] not in jobs or j.get("last_seen", "") >= jobs[j["url"]].get("last_seen", ""):
                jobs[j["url"]] = j
    db = HERE / "archive.db"
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.execute(f"CREATE TABLE jobs ({', '.join(c + (' TEXT PRIMARY KEY' if c == 'url' else ' REAL' if c in ('salary_min', 'salary_max') else ' TEXT') for c in COLUMNS)})")
    con.execute("CREATE TABLE job_skills (url TEXT REFERENCES jobs(url), skill TEXT)")
    text = lambda v: ", ".join(map(str, v)) if isinstance(v, list) else json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v
    rows = []
    for j in jobs.values():
        j = {**j, "description": j.get("desc")}
        j["salary_min"], j["salary_max"] = salary_range(j.get("salary"))
        rows.append([text(j.get(c)) for c in COLUMNS])
    con.executemany(f"INSERT INTO jobs VALUES ({', '.join('?' * len(COLUMNS))})", rows)
    con.executemany("INSERT INTO job_skills VALUES (?, ?)", [(j["url"], s) for j in jobs.values() for s in j.get("skills") or []])
    for col in ("date", "company", "source"):
        con.execute(f"CREATE INDEX jobs_{col} ON jobs({col})")
    con.execute("CREATE INDEX job_skills_skill ON job_skills(skill)")
    con.commit()
    first, last = con.execute("SELECT MIN(date), MAX(date) FROM jobs").fetchone()
    print(f"archive.db: {len(jobs)} job, thấy lần đầu từ {first} đến {last}")


if __name__ == "__main__":
    main()
