"""Turn a scraped jobs JSON file into a formatted Excel file and a readable .txt file.

Usage:
    python tools/export_jobs_excel.py .tmp/dailyremote_social-media_2026-11-08.json

Writes <same name>.xlsx and <same name>.txt next to the JSON file.
Works with any JSON that has a top-level "jobs" list (see scrape_dailyremote_jobs.py).
"""

import json
import sys
from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

COLUMNS = [
    ("#", None, 5),
    ("Job Title", "title", 38),
    ("Company", "company", 16),
    ("Job Type", "job_type", 14),
    ("Posted", "posted", 13),
    ("Location", "location", 22),
    ("Salary", "salary", 22),
    ("Experience", "experience", 13),
    ("Category", "category", 14),
    ("Role", "role", 20),
    ("Tags", "tags", 22),
    ("Summary", "summary", 70),
    ("Job Link", "url", 45),
    ("Job ID", "job_id", 10),
    ("Scraped At", "scraped_at", 16),
]

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
STRIPE_FILL = PatternFill("solid", fgColor="EEF3FA")
TITLE_FONT = Font(bold=True, size=14, color="1F3864")
LABEL_FONT = Font(bold=True)
LINK_FONT = Font(color="0563C1", underline="single")
THIN = Side(style="thin", color="C9D3E3")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
TOP_WRAP = Alignment(vertical="top", wrap_text=True)
TOP = Alignment(vertical="top")


def dup_total(data: dict) -> int:
    d = data.get("duplicates_removed", 0)
    return sum(d.values()) if isinstance(d, dict) else int(d or 0)


def summary_rows(data: dict) -> list:
    d = data.get("duplicates_removed", {})
    rows = [
        ("Source", data.get("source", "")),
        ("Search / listing", data.get("search", "")),
        ("Source URL", data.get("source_url", "")),
        ("Scraped at", data.get("scraped_at", "")),
        ("Total jobs available on site", data.get("total_available", "unknown")),
        ("Jobs in this file (unique)", len(data["jobs"])),
        ("Duplicates removed (total)", dup_total(data)),
    ]
    if isinstance(d, dict):
        rows += [
            ("  - same job ID", d.get("same_id", 0)),
            ("  - identical reposts", d.get("identical_reposts", 0)),
        ]
    with_salary = sum(1 for j in data["jobs"] if j.get("salary"))
    rows.append(("Jobs showing a salary", with_salary))
    return rows


def build_jobs_sheet(ws, jobs: list):
    ws.title = "Jobs"
    for col, (header, _, width) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill, cell.font, cell.border = HEADER_FILL, HEADER_FONT, BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.row_dimensions[1].height = 28

    for i, job in enumerate(jobs, start=1):
        r = i + 1
        for col, (header, key, _) in enumerate(COLUMNS, start=1):
            value = i if key is None else (job.get(key) or "")
            cell = ws.cell(row=r, column=col, value=value)
            cell.border = BORDER
            cell.alignment = TOP_WRAP if key in ("summary", "title", "role", "tags", "location") else TOP
            if i % 2 == 0:
                cell.fill = STRIPE_FILL
            if key in ("title", "url") and job.get("url"):
                cell.hyperlink = job["url"]
                cell.font = Font(bold=True, color="0563C1", underline="single") if key == "title" else LINK_FONT

    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{len(jobs) + 1}"


def write_counts(ws, start_row: int, title: str, counter: Counter) -> int:
    ws.cell(row=start_row, column=1, value=title).font = LABEL_FONT
    ws.cell(row=start_row, column=2, value="Jobs").font = LABEL_FONT
    for c in (1, 2):
        cell = ws.cell(row=start_row, column=c)
        cell.fill, cell.font, cell.border = HEADER_FILL, HEADER_FONT, BORDER
    r = start_row + 1
    for name, count in counter.most_common():
        ws.cell(row=r, column=1, value=name or "(not shown)").border = BORDER
        ws.cell(row=r, column=2, value=count).border = BORDER
        r += 1
    return r + 1


def build_summary_sheet(ws, data: dict):
    ws.title = "Summary"
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 60
    ws.cell(row=1, column=1, value="Job Scrape Summary").font = TITLE_FONT
    r = 3
    for label, value in summary_rows(data):
        ws.cell(row=r, column=1, value=label).font = LABEL_FONT
        cell = ws.cell(row=r, column=2, value=value)
        cell.alignment = Alignment(horizontal="left")
        if label == "Source URL":
            cell.hyperlink, cell.font = value, LINK_FONT
        r += 1
    r += 1
    jobs = data["jobs"]
    r = write_counts(ws, r, "By job type", Counter(j.get("job_type", "") for j in jobs))
    r = write_counts(ws, r, "By location", Counter(j.get("location", "") for j in jobs))
    write_counts(ws, r, "By category", Counter(j.get("category", "") for j in jobs))


def write_txt(path: Path, data: dict):
    sep = "=" * 72
    lines = [sep, "JOB LISTINGS", sep]
    for label, value in summary_rows(data):
        lines.append(f"{label:<32}: {value}")
    lines += [sep, ""]
    fields = [
        ("Company", "company"), ("Job type", "job_type"), ("Posted", "posted"),
        ("Location", "location"), ("Salary", "salary"), ("Experience", "experience"),
        ("Category", "category"), ("Role", "role"), ("Tags", "tags"),
    ]
    for i, job in enumerate(data["jobs"], start=1):
        lines.append(f"[{i}] {job.get('title', '')}")
        for label, key in fields:
            if job.get(key):
                lines.append(f"    {label:<11}: {job[key]}")
        if job.get("summary"):
            lines.append(f"    Summary    : {job['summary']}")
        lines.append(f"    Link       : {job.get('url', '')}")
        lines.append("-" * 72)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    if len(sys.argv) != 2:
        sys.exit("Usage: python tools/export_jobs_excel.py <jobs.json>")
    src = Path(sys.argv[1])
    data = json.loads(src.read_text(encoding="utf-8"))
    if not data.get("jobs"):
        sys.exit(f"No jobs found in {src}")

    wb = Workbook()
    build_jobs_sheet(wb.active, data["jobs"])
    build_summary_sheet(wb.create_sheet(), data)
    xlsx = src.with_suffix(".xlsx")
    try:
        wb.save(xlsx)
    except PermissionError:
        sys.exit(f"Cannot write {xlsx} - close it in Excel and run again.")

    txt = src.with_suffix(".txt")
    write_txt(txt, data)
    print(f"Excel: {xlsx}")
    print(f"Text:  {txt}")
    print(f"Rows:  {len(data['jobs'])}")


if __name__ == "__main__":
    main()
