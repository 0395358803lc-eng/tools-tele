import csv
import io
import unittest

import openpyxl

from backend.app.phone_import import parse_phone_file


class PhoneImportTests(unittest.TestCase):
    def test_txt(self):
        rows = parse_phone_file('phones.txt', b'0901234567\n0912345678\n')
        self.assertEqual(rows, ['0901234567', '0912345678'])

    def test_csv_phone_header(self):
        rows = parse_phone_file('phones.csv', b'name,phone\nA,0901234567\nB,+84912345678\n')
        self.assertEqual(rows, ['0901234567', '+84912345678'])

    def test_xlsx_numeric_phone_cell(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['phone'])
        ws.append([84901234567])
        buf = io.BytesIO()
        wb.save(buf)
        wb.close()
        rows = parse_phone_file('phones.xlsx', buf.getvalue())
        self.assertEqual(rows, ['84901234567'])

    def test_reject_ambiguous_multicolumn(self):
        with self.assertRaises(ValueError):
            parse_phone_file('phones.csv', b'a,b\n1,2\n')


if __name__ == '__main__':
    unittest.main()
