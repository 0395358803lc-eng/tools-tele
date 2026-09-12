from __future__ import annotations

import csv
import io
from pathlib import Path

import openpyxl
import xlrd

PHONE_HEADERS = {
    "phone", "phone_number", "phone number", "mobile", "telephone", "tel",
    "sdt", "so dien thoai", "số điện thoại", "số_điện_thoại",
}


def _header_key(value) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _rows_to_phones(rows: list[list]) -> list[str]:
    clean = [[str(cell).strip() if cell is not None else "" for cell in row] for row in rows if any(str(cell).strip() for cell in row if cell is not None)]
    if not clean:
        return []
    width = max(len(row) for row in clean)
    first = clean[0]
    match_index = next((i for i, cell in enumerate(first) if _header_key(cell) in PHONE_HEADERS), None)
    if match_index is not None:
        return [row[match_index] for row in clean[1:] if len(row) > match_index and row[match_index]]
    if width == 1:
        return [row[0] for row in clean if row and row[0]]
    raise ValueError("Tệp có nhiều cột nhưng không tìm thấy cột số điện thoại")


def parse_phone_file(filename: str, data: bytes) -> list[str]:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".txt":
        text = data.decode("utf-8-sig", errors="replace")
        out = []
        for line in text.splitlines():
            value = line.strip()
            if value:
                out.append(value)
        return out
    if suffix == ".csv":
        text = None
        for encoding in ("utf-8-sig", "utf-8", "cp1258", "latin-1"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ValueError("Không thể đọc mã hóa CSV")
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        return _rows_to_phones([list(row) for row in csv.reader(io.StringIO(text), dialect)])
    if suffix == ".xlsx":
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            ws = wb.active
            rows = [list(row) for row in ws.iter_rows(values_only=True)]
        finally:
            wb.close()
        return _rows_to_phones(rows)
    if suffix == ".xls":
        book = xlrd.open_workbook(file_contents=data)
        sheet = book.sheet_by_index(0)
        rows = [[sheet.cell_value(r, c) for c in range(sheet.ncols)] for r in range(sheet.nrows)]
        return _rows_to_phones(rows)
    raise ValueError("Chỉ hỗ trợ TXT, CSV, XLS hoặc XLSX")
