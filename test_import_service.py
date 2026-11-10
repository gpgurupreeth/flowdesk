
"""Tests for the import service layer (session lifecycle, plan, commit)."""

from datetime import datetime, timedelta, timezone

from app.services.import_service import (
    create_import_session,
    get_import_session,
    build_import_plan,
    commit_import,
)
from app.models.import_session import ImportSession
from app.models.lead import Lead
from app.schemas.import_session import ImportPlanRequest


def test_create_and_get_import_session(db, test_user):
    session = create_import_session(
        "leads.csv",
        [{"name": "A", "email": "a@example.com", "company": "C"}],
        db,
        user_id=test_user.id,
    )
    assert session.session_key
    assert session.status == "pending"
    assert session.import_plan["total_rows"] == 1
    assert session.user_id == test_user.id

    fetched = get_import_session(session.session_key, db, user_id=test_user.id)
    assert fetched is not None
    assert fetched.session_key == session.session_key


def test_get_missing_session_returns_none(db, test_user):
    assert get_import_session("nonexistent-key", db, user_id=test_user.id) is None


def test_build_import_plan_creates_and_updates(db, test_user):
    session = create_import_session(
        "leads.csv",
        [
            {"name": "New User", "email": "new@example.com", "company": "New Co"},
            {
                "name": "Existing User",
                "email": "existing@example.com",
                "company": "Existing Co",
                "phone": "",
            },
        ],
        db,
        user_id=test_user.id,
    )

    # Seed an existing lead owned by the same user
    existing = Lead(
        user_id=test_user.id,
        name="Existing User",
        email="existing@example.com",
        company="Existing Co",
        phone="5555555555",
        location="Old City",
    )
    db.add(existing)
    db.commit()

    plan = build_import_plan(
        session.session_key,
        ImportPlanRequest(
            session_key=session.session_key,
            mapping={
                "name": "name",
                "email": "email",
                "company": "company",
                "phone": "phone",
                "location": "location",
            },
            custom_fields={},
        ),
        db,
        user_id=test_user.id,
    )

    assert plan["total_rows"] == 2
    assert plan["summary"]["create"] == 1
    assert plan["summary"]["update"] == 1

    create_row = plan["rows"][0]
    assert create_row["action"] == "create"
    assert create_row["existing_lead_id"] is None

    update_row = plan["rows"][1]
    assert update_row["action"] == "update"
    assert update_row["existing_lead_id"] == existing.id
    assert "location" in update_row["preserve_existing_fields"]


def test_build_import_plan_phone_conflict_requires_review(db, test_user):
    session = create_import_session(
        "leads.csv",
        [
            {"name": "User", "email": "user@example.com", "company": "Co",
             "phone": "9999999999"},
        ],
        db,
        user_id=test_user.id,
    )
    existing = Lead(
        user_id=test_user.id,
        name="User",
        email="user@example.com",
        company="Co",
        phone="1111111111",
    )
    db.add(existing)
    db.commit()

    plan = build_import_plan(
        session.session_key,
        ImportPlanRequest(
            session_key=session.session_key,
            mapping={
                "name": "name",
                "email": "email",
                "company": "company",
                "phone": "phone",
            },
            custom_fields={},
        ),
        db,
        user_id=test_user.id,
    )

    row = plan["rows"][0]
    assert row["action"] == "review"
    assert any("phone" in reason.lower() for reason in row["review_reasons"])


def test_commit_import_creates_lead_and_custom_fields(db, test_user):
    session = create_import_session(
        "leads.csv",
        [
            {
                "name": "New User",
                "email": "new@example.com",
                "company": "New Co",
                "phone": "1234567890",
            },
        ],
        db,
        user_id=test_user.id,
    )

    build_import_plan(
        session.session_key,
        ImportPlanRequest(
            session_key=session.session_key,
            mapping={
                "name": "name",
                "email": "email",
                "company": "company",
                "phone": "phone",
            },
            custom_fields={},
        ),
        db,
        user_id=test_user.id,
    )

    result = commit_import(session.session_key, db, user_id=test_user.id)

    assert result["status"] == "completed"
    assert result["created"] == 1
    assert result["updated"] == 0
    assert len(result["leads"]) == 1
    assert result["leads"][0]["name"] == "New User"

    # Verify the lead exists in the database and is owned by the user
    lead = db.query(Lead).filter(Lead.email == "new@example.com").first()
    assert lead is not None
    assert lead.name == "New User"
    assert lead.user_id == test_user.id


def test_commit_import_is_idempotent(db, test_user):
    session = create_import_session(
        "leads.csv",
        [
            {"name": "User", "email": "user@example.com", "company": "Co"},
        ],
        db,
        user_id=test_user.id,
    )
    build_import_plan(
        session.session_key,
        ImportPlanRequest(
            session_key=session.session_key,
            mapping={
                "name": "name",
                "email": "email",
                "company": "company",
            },
            custom_fields={},
        ),
        db,
        user_id=test_user.id,
    )

    result1 = commit_import(session.session_key, db, user_id=test_user.id)
    assert result1["already_committed"] is False
    assert result1["created"] == 1

    result2 = commit_import(session.session_key, db, user_id=test_user.id)
    assert result2["already_committed"] is True
    assert result2["created"] == 0
    assert result2["leads"] == []

    # Only one lead in the database
    count = db.query(Lead).filter(Lead.email == "user@example.com").count()
    assert count == 1


def test_commit_review_rows_are_skipped(db, test_user):
    session = create_import_session(
        "leads.csv",
        [
            {"name": "User", "email": "user@example.com", "company": "Co",
             "phone": "9999999999"},
        ],
        db,
        user_id=test_user.id,
    )
    existing = Lead(
        user_id=test_user.id,
        name="User", email="user@example.com", company="Co",
        phone="1111111111"
    )
    db.add(existing)
    db.commit()

    build_import_plan(
        session.session_key,
        ImportPlanRequest(
            session_key=session.session_key,
            mapping={
                "name": "name",
                "email": "email",
                "company": "company",
                "phone": "phone",
            },
            custom_fields={},
        ),
        db,
        user_id=test_user.id,
    )

    result = commit_import(session.session_key, db, user_id=test_user.id)
    assert result["reviewed"] == 1
    assert result["created"] == 0
    assert result["updated"] == 0

    # Lead unchanged
    lead = db.query(Lead).filter(Lead.email == "user@example.com").first()
    assert lead.phone == "1111111111"


def test_commit_expired_session_fails(db, test_user):
    session = create_import_session(
        "leads.csv",
        [{"name": "User", "email": "user@example.com", "company": "Co"}],
        db,
        user_id=test_user.id,
    )
    # Expire the session
    session.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    try:
        commit_import(session.session_key, db, user_id=test_user.id)
        assert False, "Expected ValueError for expired session"
    except ValueError as exc:
        assert "expired" in str(exc).lower()


def test_build_import_plan_missing_session_raises(db, test_user):
    try:
        build_import_plan(
            "nonexistent-key",
            ImportPlanRequest(
                session_key="nonexistent-key",
                mapping={},
                custom_fields={},
            ),
            db,
            user_id=test_user.id,
        )
        assert False, "Expected ValueError for missing session"
    except ValueError as exc:
        assert "not found" in str(exc).lower()


def test_import_session_model_fields(db, test_user):
    session = create_import_session(
        "test.csv",
        [{"name": "A", "email": "a@example.com", "company": "C"}],
        db,
        user_id=test_user.id,
    )
    assert isinstance(session.id, int)
    assert session.filename == "test.csv"
    assert session.status == "pending"
    assert session.user_id == test_user.id
    assert session.created_at is not None
    assert session.expires_at is not None
    assert session.committed_at is None
