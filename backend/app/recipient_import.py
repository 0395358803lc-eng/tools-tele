from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Iterable


HEADER_ALIASES = {
    "target", "recipient", "receiver", "username", "user_name", "user name",
    "usname", "telegram", "telegram_username", "telegram username",
    "phone", "phone_number", "phone number", "mobile", "telephone",
    "số điện thoại", "so dien thoai", "sdt",
}


def _clean_header(value) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _extract_from_rows(rows: list[list[object]]) -> tuple[list[str], list[str], int]:
    rows = [list(r) for r in rows if any(_stringify(v) for v in r)]
    if not rows:
        raise ValueError("Tệp không có dữ liệu người nhận")

    header = [_clean_header(v) for v in rows[0]]
    matched = [i for i, name in enumerate(header) if name in HEADER_ALIASES]
    data_rows = rows[1:] if matched else rows
    if not matched:
        width = max(len(r) for r in rows)
        if width != 1:
            raise ValueError(
                "Không xác định được cột người nhận. Hãy đặt tên cột là username, usname, phone, số điện thoại hoặc target."
            )
        matched = [0]

    out: list[str] = []
    for row in data_rows:
        for idx in matched:
            if idx < len(row):
                value = _stringify(row[idx])
                if value:
                    out.append(value)
    if not out:
        raise ValueError("Không tìm thấy username hoặc số điện thoại trong tệp")
    cols = [header[i] for i in matched if i < len(header) and header[i]]
    return out, cols, len(data_rows)


def parse_recipient_file(filename: str, data: bytes) -> dict:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".csv":
        text = None
        for enc in ("utf-8-sig", "utf-8", "cp1258", "latin-1"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ValueError("Không thể đọc mã hóa của tệp CSV")
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = [list(r) for r in csv.reader(io.StringIO(text), dialect)]
    elif suffix == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            ws = wb.active
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
        finally:
            wb.close()
    elif suffix == ".xls":
        import xlrd
        book = xlrd.open_workbook(file_contents=data)
        sheet = book.sheet_by_index(0)
        rows = [sheet.row_values(i) for i in range(sheet.nrows)]
    else:
        raise ValueError("Chỉ hỗ trợ tệp .csv, .xlsx hoặc .xls")

    raw, columns, row_count = _extract_from_rows(rows)
    return {"raw_targets": raw, "columns": columns, "rows": row_count}
