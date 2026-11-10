from app.services.lead_import_validator import validate_import_rows


def test_valid_lead_and_custom_field():
    rows = [{
        "Name": "Rahul Sharma",
        "Email": "rahul@example.com",
        "Company": "Acme",
        "Campaign": "LinkedIn",
    }]

    mapping = {
        "Name": "name",
        "Email": "email",
        "Company": "company",
        "Campaign": "__custom__",
    }

    custom_fields = {
        "Campaign": {
            "name": "Campaign Source",
            "type": "text",
        }
    }

    result = validate_import_rows(rows, mapping, custom_fields)

    assert result["valid_rows"] == 1
    assert result["invalid_rows"] == 0
    assert result["rows"][0]["custom_values"]["Campaign Source"] == "LinkedIn"


def test_missing_required_field():
    rows = [{
        "Name": "Rahul",
        "Email": "rahul@example.com",
        "Company": "",
    }]

    mapping = {
        "Name": "name",
        "Email": "email",
        "Company": "company",
    }

    result = validate_import_rows(rows, mapping, {})

    assert result["invalid_rows"] == 1
    assert any("company" in error["message"] for error in result["errors"])


def test_duplicate_emails_with_different_case():
    rows = [
        {"Name": "Rahul", "Email": "rahul@example.com", "Company": "Acme"},
        {"Name": "Rahul Updated", "Email": "RAHUL@example.com", "Company": "Acme"},
    ]

    mapping = {
        "Name": "name",
        "Email": "email",
        "Company": "company",
    }

    result = validate_import_rows(rows, mapping, {})

    assert result["invalid_rows"] == 2
    assert len(result["duplicate_emails"]) == 1


def test_invalid_custom_number():
    rows = [{
        "Name": "Priya",
        "Email": "priya@example.com",
        "Company": "Bright",
        "Budget": "many",
    }]

    mapping = {
        "Name": "name",
        "Email": "email",
        "Company": "company",
        "Budget": "__custom__",
    }

    custom_fields = {
        "Budget": {
            "name": "Budget",
            "type": "number",
        }
    }

    result = validate_import_rows(rows, mapping, custom_fields)

    assert result["invalid_rows"] == 1
    assert any("Budget" in error["message"] for error in result["errors"])


def test_invalid_email():
    rows = [{
        "Name": "Rahul",
        "Email": "not-an-email",
        "Company": "Acme",
    }]

    mapping = {
        "Name": "name",
        "Email": "email",
        "Company": "company",
    }

    result = validate_import_rows(rows, mapping, {})

    assert result["invalid_rows"] == 1
    assert any("email" in error["message"].lower() for error in result["errors"])


def test_invalid_custom_date():
    rows = [{
        "Name": "Priya",
        "Email": "priya@example.com",
        "Company": "Bright",
        "Date": "not-a-date",
    }]

    mapping = {
        "Name": "name",
        "Email": "email",
        "Company": "company",
        "Date": "__custom__",
    }

    custom_fields = {
        "Date": {
            "name": "Follow-up Date",
            "type": "date",
        }
    }

    result = validate_import_rows(rows, mapping, custom_fields)

    assert result["invalid_rows"] == 1
    assert any("date" in error["message"].lower() for error in result["errors"])


def test_invalid_custom_checkbox():
    rows = [{
        "Name": "Priya",
        "Email": "priya@example.com",
        "Company": "Bright",
        "OptIn": "maybe",
    }]

    mapping = {
        "Name": "name",
        "Email": "email",
        "Company": "company",
        "OptIn": "__custom__",
    }

    custom_fields = {
        "OptIn": {
            "name": "Opt In",
            "type": "checkbox",
        }
    }

    result = validate_import_rows(rows, mapping, custom_fields)

    assert result["invalid_rows"] == 1
    assert any("checkbox" in error["message"].lower() for error in result["errors"])


def test_empty_custom_values_are_skipped():
    rows = [{
        "Name": "Rahul",
        "Email": "rahul@example.com",
        "Company": "Acme",
        "Campaign": "",
    }]

    mapping = {
        "Name": "name",
        "Email": "email",
        "Company": "company",
        "Campaign": "__custom__",
    }

    custom_fields = {
        "Campaign": {
            "name": "Campaign Source",
            "type": "text",
        }
    }

    result = validate_import_rows(rows, mapping, custom_fields)

    assert result["invalid_rows"] == 0
    assert result["rows"][0]["custom_values"] == {}


def test_checkbox_valid_representations():
    rows = [{
        "Name": "Rahul",
        "Email": "rahul@example.com",
        "Company": "Acme",
        "OptIn": "true",
    }]

    mapping = {
        "Name": "name",
        "Email": "email",
        "Company": "company",
        "OptIn": "__custom__",
    }

    custom_fields = {
        "OptIn": {
            "name": "Opt In",
            "type": "checkbox",
        }
    }

    result = validate_import_rows(rows, mapping, custom_fields)

    assert result["invalid_rows"] == 0
    assert result["rows"][0]["custom_values"]["Opt In"] == "true"


def test_number_valid_representations():
    rows = [{
        "Name": "Priya",
        "Email": "priya@example.com",
        "Company": "Bright",
        "Budget": "1,500.50",
    }]

    mapping = {
        "Name": "name",
        "Email": "email",
        "Company": "company",
        "Budget": "__custom__",
    }

    custom_fields = {
        "Budget": {
            "name": "Budget",
            "type": "number",
        }
    }

    result = validate_import_rows(rows, mapping, custom_fields)

    # float("1,500.50") raises ValueError due to comma
    assert result["invalid_rows"] == 1


def test_date_valid_iso_format():
    rows = [{
        "Name": "Priya",
        "Email": "priya@example.com",
        "Company": "Bright",
        "Date": "2024-01-15",
    }]

    mapping = {
        "Name": "name",
        "Email": "email",
        "Company": "company",
        "Date": "__custom__",
    }

    custom_fields = {
        "Date": {
            "name": "Follow-up",
            "type": "date",
        }
    }

    result = validate_import_rows(rows, mapping, custom_fields)

    assert result["invalid_rows"] == 0
    assert result["rows"][0]["custom_values"]["Follow-up"] == "2024-01-15"
