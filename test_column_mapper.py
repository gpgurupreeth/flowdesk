
import unittest

from app.utils.column_mapper import (
    CUSTOM_FIELD,
    build_custom_field_configs,
    detect_column_mapping,
)


class TestColumnMapper(unittest.TestCase):
    def test_detect_common_headers(self):
        result = detect_column_mapping(
            ["Full Name", "Email Address", "Company Name", "Phone No."]
        )

        self.assertEqual(result["Full Name"], "name")
        self.assertEqual(result["Email Address"], "email")
        self.assertEqual(result["Company Name"], "company")
        self.assertEqual(result["Phone No."], "phone")

    def test_unknown_header_remains_unmapped(self):
        result = detect_column_mapping(
            ["Full Name", "Campaign Source"]
        )

        self.assertEqual(result["Full Name"], "name")
        # Unknown columns are auto-mapped to a custom field.
        self.assertEqual(result["Campaign Source"], "__custom__")

    def test_duplicate_destination_is_not_assigned_twice(self):
        result = detect_column_mapping(
            ["Email", "Email Address"]
        )

        self.assertEqual(result["Email"], "email")
        # Duplicate standard field is auto-mapped to a custom field.
        self.assertEqual(result["Email Address"], "__custom__")


class TestBuildCustomFieldConfigs(unittest.TestCase):
    def test_auto_creates_custom_fields_for_unmapped_columns(self):
        headers = ["Full Name", "Email Address", "Campaign Source", "Budget"]
        mapping = {
            "Full Name": "name",
            "Email Address": "email",
            "Campaign Source": "__custom__",
            "Budget": "__custom__",
        }

        configs = build_custom_field_configs(headers, mapping)

        self.assertIn("Campaign Source", configs)
        self.assertIn("Budget", configs)
        self.assertNotIn("Full Name", configs)
        self.assertNotIn("Email Address", configs)
        self.assertEqual(configs["Campaign Source"]["name"], "Campaign Source")
        self.assertEqual(configs["Campaign Source"]["type"], "text")
        self.assertEqual(configs["Budget"]["name"], "Budget")
        self.assertEqual(configs["Budget"]["type"], "text")

    def test_duplicate_column_names_get_unique_custom_field_names(self):
        headers = ["Campaign", "Campaign"]
        mapping = {
            "Campaign": "__custom__",
        }

        configs = build_custom_field_configs(headers, mapping)

        self.assertEqual(len(configs), 1)
        # Only one entry since both columns share the same header key.


if __name__ == "__main__":
    unittest.main()
