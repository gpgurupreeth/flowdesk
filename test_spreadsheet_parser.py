import unittest

from app.utils.spreadsheet_parser import parse_spreadsheet


class TestSpreadsheetParser(unittest.TestCase):
    def test_parse_csv(self):
        content = (
            "Full Name,Email Address,Company Name\n"
            "Rahul Sharma,rahul@example.com,Acme Technologies\n"
        ).encode("utf-8")

        rows = parse_spreadsheet("leads.csv", content)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Full Name"], "Rahul Sharma")
        self.assertEqual(rows[0]["Email Address"], "rahul@example.com")

    def test_parse_xlsx(self):
        import openpyxl
        from io import BytesIO

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["Name", "Email", "Company"])
        sheet.append(["Priya", "priya@example.com", "Bright"])

        buffer = BytesIO()
        workbook.save(buffer)
        content = buffer.getvalue()

        rows = parse_spreadsheet("leads.xlsx", content)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Name"], "Priya")
        self.assertEqual(rows[0]["Email"], "priya@example.com")

    def test_reject_unsupported_file(self):
        with self.assertRaises(ValueError):
            parse_spreadsheet("leads.pdf", b"test content")

    def test_reject_empty_file(self):
        with self.assertRaises(ValueError):
            parse_spreadsheet("leads.csv", b"")

    def test_reject_duplicate_headers(self):
        content = (
            "Email,email\n"
            "a@example.com,b@example.com\n"
        ).encode("utf-8")

        with self.assertRaises(ValueError):
            parse_spreadsheet("leads.csv", content)

    def test_reject_blank_header(self):
        content = (
            "Name,,Company\n"
            "Rahul,rahul@example.com,Acme\n"
        ).encode("utf-8")

        with self.assertRaises(ValueError):
            parse_spreadsheet("leads.csv", content)

    def test_handles_empty_cells(self):
        content = (
            "Name,Email,Company,Phone\n"
            "Rahul,rahul@example.com,Acme,\n"
            ",,,\n"
        ).encode("utf-8")

        rows = parse_spreadsheet("leads.csv", content)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Phone"], "")
        self.assertEqual(rows[1]["Name"], "")

    def test_reject_malformed_csv(self):
        # Not a valid CSV/UTF-8
        content = b"\xff\xfe\x00\x00invalid"
        with self.assertRaises(ValueError):
            parse_spreadsheet("leads.csv", content)

    def test_row_count_limit(self):
        # Build a CSV with more than 10,000 rows
        lines = ["Name,Email,Company"]
        for i in range(10_001):
            lines.append(f"User{i},user{i}@example.com,Co{i}")
        content = "\n".join(lines).encode("utf-8")

        with self.assertRaises(ValueError) as ctx:
            parse_spreadsheet("leads.csv", content)

        self.assertIn("10000", str(ctx.exception))

    def test_file_size_limit(self):
        # Content larger than 10 MB
        content = b"x" * (10 * 1024 * 1024 + 1)
        with self.assertRaises(ValueError) as ctx:
            parse_spreadsheet("leads.csv", content)

        self.assertIn("10 MB", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
