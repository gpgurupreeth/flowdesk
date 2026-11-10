
import re
from collections import defaultdict
from email_validator import EmailNotValidError, validate_email


REQUIRED_FIELDS = {"name", "email", "company"}

SUPPORTED_CUSTOM_TYPES = {"text", "number", "date", "checkbox"}


def normalize_email(value: str | None) -> str | None:
    if not value or not value.strip():
        return None

    return value.strip().casefold()


def validate_email_value(value: str) -> bool:
    try:
        validate_email(value.strip(), check_deliverability=False)
        return True
    except EmailNotValidError:
        return False


def validate_custom_value(value: str, field_type: str) -> bool:
    if field_type not in SUPPORTED_CUSTOM_TYPES:
        return False

    if field_type == "number":
        try:
            float(value)
            return True
        except ValueError:
            return False

    if field_type == "date":
        from datetime import date

        try:
            date.fromisoformat(value)
            return True
        except ValueError:
            return False

    if field_type == "checkbox":
        return value.casefold() in {"true", "false", "yes", "no", "1", "0"}

    return True


def validate_import_rows(
    rows: list[dict[str, str]],
    mapping: dict[str, str | None],
    custom_fields: dict[str, dict[str, str]],
) -> dict:
    validated_rows = []
    errors = []
    email_rows = defaultdict(list)

    for row_number, row in enumerate(rows, start=1):
        lead = {}
        custom_values = {}
        row_errors = []

        for source_column, destination in mapping.items():
            value = (row.get(source_column) or "").strip()

            if not destination or destination == "__custom__":
                continue

            if destination in REQUIRED_FIELDS and not value:
                row_errors.append(
                    f"Required field '{destination}' is empty."
                )

            if destination == "email" and value:
                if not validate_email_value(value):
                    row_errors.append("Invalid email address.")
                else:
                    email_rows[normalize_email(value)].append(row_number)

            lead[destination] = value or None

        # Ensure every required field is present in the lead data, even if no
        # spreadsheet column was mapped to it (e.g. the column doesn't exist).
        for required_field in REQUIRED_FIELDS:
            if not lead.get(required_field):
                row_errors.append(
                    f"Required field '{required_field}' is missing or empty."
                )

        for source_column, definition in custom_fields.items():
            value = (row.get(source_column) or "").strip()

            if not value:
                continue

            field_name = definition.get("name", "").strip()
            field_type = definition.get("type", "text")

            if not field_name:
                row_errors.append(
                    f"Custom field for '{source_column}' has no name."
                )
                continue

            if not validate_custom_value(value, field_type):
                row_errors.append(
                    f"Invalid {field_type} value for '{field_name}'."
                )
                continue

            custom_values[field_name] = value

        validated_rows.append({
            "row_number": row_number,
            "lead": lead,
            "custom_values": custom_values,
            "errors": row_errors,
        })

        for message in row_errors:
            errors.append({
                "row_number": row_number,
                "message": message,
            })

    duplicate_emails = {
        email: row_numbers
        for email, row_numbers in email_rows.items()
        if len(row_numbers) > 1
    }

    for email, row_numbers in duplicate_emails.items():
        for row_number in row_numbers:
            message = (
                f"Email '{email}' appears more than once in the spreadsheet."
            )

            validated_rows[row_number - 1]["errors"].append(message)
            errors.append({
                "row_number": row_number,
                "message": message,
            })

    return {
        "total_rows": len(rows),
        "valid_rows": sum(
            1 for row in validated_rows if not row["errors"]
        ),
        "invalid_rows": sum(
            1 for row in validated_rows if row["errors"]
        ),
        "rows": validated_rows,
        "errors": errors,
        "duplicate_emails": duplicate_emails,
    }
