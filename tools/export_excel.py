"""Turn any scraper dataset JSON (see common/dataset.py) into a formatted Excel file.

Usage:
    python tools/export_excel.py .tmp/books_all-books_2026-11-09.json

Writes <same name>.xlsx next to the JSON. Sheet "Data": one row per item, columns
from the dataset's `columns` list (numbers stored as real numbers, links clickable,
frozen header, auto-filter). Sheet "Summary": run details, filters, rows removed
and blank-value counts per column.
(Generalized from the old job-only export_jobs_excel.py - same styling.)
"""

import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import dataset  # noqa: E402

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
NUMERIC = {"number", "money", "rating", "percent"}


def number_format(col, items):
    vals = [i.get(col["key"]) for i in items if isinstance(i.get(col["key"]), (int, float))]
    whole = all(float(v).is_integer() for v in vals)
    return {
        "money": "#,##0" if whole else "#,##0.00",
        "number": "#,##0" if whole else "#,##0.##",
        "rating": "0.0",
        "percent": '0"%"',
    }.get(col["type"])


def cell_value(v, ctype):
    if v is None or v == [] or v == "":
        return None
    if isinstance(v, list):
        return ", ".join(map(str, v))
    if ctype == "bool" or isinstance(v, bool):
        return "Yes" if v else "No"
    return v


def summary_rows(meta, n_rows):
    rows = [
        ("Request", meta.get("description") or "(none given)"),
        ("Source URL", meta.get("source_url")),
        ("Scraped at", meta.get("scraped_at")),
        ("Rows in this file", n_rows),
        ("Items seen on the site", meta.get("items_seen")),
        ("Duplicates removed", meta.get("duplicates_removed")),
        ("Removed by filters", sum((meta.get("filtered_out") or {}).values())),
        ("Pages fetched", meta.get("pages_fetched")),
        ("Stopped because", meta.get("stopped_because")),
        ("Fetch method", meta.get("method")),
        ("Extractor", meta.get("extractor")),
        ("Firecrawl credits used", meta.get("firecrawl_credits_used", 0)),
        ("Filters", json.dumps(meta.get("filters"), ensure_ascii=False) if meta.get("filters") else "none"),
    ]
    return rows


def header(ws, row, labels):
    for c, label in enumerate(labels, start=1):
        cell = ws.cell(row=row, column=c, value=label)
        cell.fill, cell.font, cell.border = HEADER_FILL, HEADER_FONT, BORDER


def build_data_sheet(ws, columns, items):
    ws.title = "Data"
    cols = [{"key": None, "label": "#", "type": "number", "width": 6}] + columns
    url_key = next((c["key"] for c in columns if c["type"] == "url"), None)
    first_text = next((c["key"] for c in columns if c["type"] == "text"), None)
    formats = {c["key"]: number_format(c, items) for c in columns if c["type"] in NUMERIC}
    for c, col in enumerate(cols, start=1):
        cell = ws.cell(row=1, column=c, value=col["label"])
        cell.fill, cell.font, cell.border = HEADER_FILL, HEADER_FONT, BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(c)].width = col.get("width", 20)
    ws.row_dimensions[1].height = 30
    for i, item in enumerate(items, start=1):
        r = i + 1
        for c, col in enumerate(cols, start=1):
            key = col["key"]
            v = i if key is None else cell_value(item.get(key), col["type"])
            cell = ws.cell(row=r, column=c, value=v)
            cell.border = BORDER
            cell.alignment = TOP_WRAP if col["type"] in ("text", "list") else TOP
            if i % 2 == 0:
                cell.fill = STRIPE_FILL
            if key in formats and formats[key]:
                cell.number_format = formats[key]
            if col["type"] == "url" and v:
                cell.hyperlink, cell.font = v, LINK_FONT
            elif key == first_text and url_key and item.get(url_key):
                cell.hyperlink = item[url_key]
                cell.font = Font(bold=True, color="0563C1", underline="single")
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{len(items) + 1}"


def build_summary_sheet(ws, data):
    meta, columns = data["meta"], data["columns"]
    ws.title = "Summary"
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 70
    ws.cell(row=1, column=1, value="Scrape Summary").font = TITLE_FONT
    r = 3
    for label, value in summary_rows(meta, len(data["items"])):
        ws.cell(row=r, column=1, value=label).font = LABEL_FONT
        cell = ws.cell(row=r, column=2, value=value)
        cell.alignment = Alignment(horizontal="left", wrap_text=True)
        if label == "Source URL" and value:
            cell.hyperlink, cell.font = value, LINK_FONT
        r += 1
    r += 1
    header(ws, r, ["Column", "Blank values (left empty, never guessed)"])
    missing = meta.get("missing_values") or dataset.missing_counts(data["items"], columns)
    for col in columns:
        r += 1
        ws.cell(row=r, column=1, value=col["label"]).border = BORDER
        ws.cell(row=r, column=2, value=missing.get(col["key"], 0)).border = BORDER
    if meta.get("filtered_out"):
        r += 2
        header(ws, r, ["Removed by filter (reason)", "Items"])
        for reason, n in sorted(meta["filtered_out"].items(), key=lambda x: -x[1]):
            r += 1
            ws.cell(row=r, column=1, value=reason).border = BORDER
            ws.cell(row=r, column=2, value=n).border = BORDER
        ws.column_dimensions["A"].width = 55


def export(src) -> Path:
    src = Path(src)
    data = dataset.read(src)
    wb = Workbook()
    build_data_sheet(wb.active, data["columns"], data["items"])
    build_summary_sheet(wb.create_sheet(), data)
    xlsx = src.with_suffix(".xlsx")
    try:
        wb.save(xlsx)
    except PermissionError:
        sys.exit(f"Cannot write {xlsx} - close it in Excel and run again.")
    return xlsx


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    if len(sys.argv) != 2:
        sys.exit("Usage: python tools/export_excel.py <dataset.json>")
    print(f"Excel: {export(sys.argv[1])}")


if __name__ == "__main__":
    main()
