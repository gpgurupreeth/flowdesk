
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.lead_import_matcher import classify_import_rows


def test_existing_email_is_classified_as_update():
    db = MagicMock()
    existing_lead = SimpleNamespace(
        id=12,
        email="rahul@example.com",
        phone=None,
    )
    db.scalars.return_value.all.return_value = [existing_lead]

    rows = [{
        "row_number": 1,
        "lead": {
            "name": "Rahul Updated",
            "email": "RAHUL@example.com",
            "company": "Acme",
        },
        "custom_values": {},
        "errors": [],
    }]

    result = classify_import_rows(rows, db)

    assert result[0]["action"] == "update"
    assert result[0]["existing_lead_id"] == 12


def test_new_email_is_classified_as_create():
    db = MagicMock()
    db.scalars.return_value.all.return_value = []

    rows = [{
        "row_number": 1,
        "lead": {
            "name": "Priya",
            "email": "priya@example.com",
            "company": "Bright",
        },
        "custom_values": {},
        "errors": [],
    }]

    result = classify_import_rows(rows, db)

    assert result[0]["action"] == "create"
    assert result[0]["existing_lead_id"] is None


def test_invalid_row_is_sent_for_review():
    db = MagicMock()

    rows = [{
        "row_number": 1,
        "lead": {"email": "invalid-email"},
        "custom_values": {},
        "errors": ["Invalid email address."],
    }]

    result = classify_import_rows(rows, db)

    assert result[0]["action"] == "review"
    assert db.scalars.call_count == 0


def test_conflicting_phone_number_requires_review():
    db = MagicMock()
    existing_lead = SimpleNamespace(
        id=12,
        email="rahul@example.com",
        phone="9876543210",
    )
    db.scalars.return_value.all.return_value = [existing_lead]

    rows = [{
        "row_number": 1,
        "lead": {
            "name": "Rahul",
            "email": "rahul@example.com",
            "company": "Acme",
            "phone": "9999999999",
            "location": "",
        },
        "custom_values": {},
        "errors": [],
    }]

    result = classify_import_rows(rows, db)

    assert result[0]["action"] == "review"
    assert result[0]["existing_lead_id"] == 12
    assert len(result[0]["review_reasons"]) == 1


def test_same_phone_with_different_format_does_not_conflict():
    db = MagicMock()
    existing_lead = SimpleNamespace(
        id=12,
        email="rahul@example.com",
        phone="+91 98765-43210",
    )
    db.scalars.return_value.all.return_value = [existing_lead]

    rows = [{
        "row_number": 1,
        "lead": {
            "name": "Rahul",
            "email": "rahul@example.com",
            "company": "Acme",
            "phone": "919876543210",
            "location": "",
        },
        "custom_values": {},
        "errors": [],
    }]

    result = classify_import_rows(rows, db)

    assert result[0]["action"] == "update"
    assert result[0]["review_reasons"] == []


def test_ambiguous_phone_match_is_sent_for_review():
    db = MagicMock()
    existing_leads = [
        SimpleNamespace(id=12, email="rahul@example.com", phone="9876543210"),
        SimpleNamespace(id=15, email="priya@example.com", phone="98765-43210"),
    ]
    db.scalars.return_value.all.return_value = existing_leads

    rows = [{
        "row_number": 1,
        "lead": {
            "name": "New Person",
            "email": "",
            "company": "Bright",
            "phone": "9876543210",
        },
        "custom_values": {},
        "errors": [],
    }]

    result = classify_import_rows(rows, db)

    assert result[0]["action"] == "review"
    assert result[0]["existing_lead_id"] is None
    assert result[0]["matched_by"] is None
    assert len(result[0]["review_reasons"]) == 1


def test_blank_imported_fields_are_preserved():
    db = MagicMock()
    existing_lead = SimpleNamespace(
        id=12,
        email="rahul@example.com",
        phone="9876543210",
    )
    db.scalars.return_value.all.return_value = [existing_lead]

    rows = [{
        "row_number": 1,
        "lead": {
            "name": "Rahul",
            "email": "rahul@example.com",
            "company": "Acme",
            "phone": "",
            "location": "",
        },
        "custom_values": {},
        "errors": [],
    }]

    result = classify_import_rows(rows, db)

    assert result[0]["action"] == "update"
    assert "phone" in result[0]["preserve_existing_fields"]
    assert "location" in result[0]["preserve_existing_fields"]
