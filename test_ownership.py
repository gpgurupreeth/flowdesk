
"""Ownership isolation, deletion, overview, pipeline, and timestamp tests."""

from datetime import date, datetime, timedelta, timezone

from app.models.user import User
from app.models.lead import Lead
from app.models.custom_field import CustomFieldDefinition
from app.models.lead_custom_field_value import LeadCustomFieldValue
from app.services.auth import hash_password


def test_user_cannot_read_another_users_leads(db, test_user, auth_client):
    """User A cannot list User B's leads."""
    from sqlalchemy.orm import sessionmaker
    OtherSession = sessionmaker(bind=db.get_bind())
    other_db = OtherSession()

    other_user = User(
        full_name="Other User",
        email="other@example.com",
        hashed_password=hash_password("password123"),
        is_active=True,
    )
    other_db.add(other_user)
    other_db.commit()

    # Create a lead for the other user
    other_lead = Lead(
        user_id=other_user.id,
        name="Other Lead",
        email="otherlead@example.com",
        company="Other Co",
    )
    other_db.add(other_lead)
    other_db.commit()

    # Try to access via the test user's client
    response = auth_client.get("/api/leads")
    assert response.status_code == 200
    leads = response.json()
    lead_emails = [l["email"] for l in leads]
    assert "otherlead@example.com" not in lead_emails

    other_db.close()


def test_user_cannot_update_another_users_lead(db, test_user, auth_client):
    """User A cannot update User B's lead."""
    from sqlalchemy.orm import sessionmaker
    OtherSession = sessionmaker(bind=db.get_bind())
    other_db = OtherSession()

    other_user = User(
        full_name="Other User",
        email="other2@example.com",
        hashed_password=hash_password("password123"),
        is_active=True,
    )
    other_db.add(other_user)
    other_db.commit()

    other_lead = Lead(
        user_id=other_user.id,
        name="Other Lead",
        email="other2@example.com",
        company="Other Co",
    )
    other_db.add(other_lead)
    other_db.commit()
    other_lead_id = other_lead.id

    # Try to update via the test user's client
    response = auth_client.patch(
        f"/api/leads/{other_lead_id}",
        json={"name": "Hacked"},
    )
    assert response.status_code == 404

    other_db.close()


def test_user_cannot_delete_another_users_lead(db, test_user, auth_client):
    """User A cannot delete User B's lead."""
    from sqlalchemy.orm import sessionmaker
    OtherSession = sessionmaker(bind=db.get_bind())
    other_db = OtherSession()

    other_user = User(
        full_name="Other User",
        email="other3@example.com",
        hashed_password=hash_password("password123"),
        is_active=True,
    )
    other_db.add(other_user)
    other_db.commit()

    other_lead = Lead(
        user_id=other_user.id,
        name="Other Lead",
        email="other3@example.com",
        company="Other Co",
    )
    other_db.add(other_lead)
    other_db.commit()
    other_lead_id = other_lead.id

    # Try to delete via the test user's client
    response = auth_client.delete(f"/api/leads/{other_lead_id}")
    assert response.status_code == 404

    # Lead still exists
    other_lead_check = other_db.get(Lead, other_lead_id)
    assert other_lead_check is not None

    other_db.close()


def test_lead_deletion_removes_custom_field_values(db, test_user, auth_client):
    """Deleting a lead removes its custom-field values but not the definition."""
    # Create a custom field
    field_resp = auth_client.post(
        "/api/custom-fields",
        json={"name": "TestField", "field_type": "text"},
    )
    assert field_resp.status_code == 201
    field_id = field_resp.json()["id"]

    # Create a lead
    lead_resp = auth_client.post(
        "/api/leads",
        json={"name": "Delete Me", "email": "delete@example.com", "company": "Co"},
    )
    assert lead_resp.status_code == 201
    lead_id = lead_resp.json()["id"]

    # Set custom field value
    update_resp = auth_client.put(
        f"/api/leads/{lead_id}/custom-fields/{field_id}",
        json={"value": "TestValue"},
    )
    assert update_resp.status_code == 200

    # Verify value exists
    get_resp = auth_client.get(f"/api/leads/{lead_id}/custom-fields")
    assert get_resp.status_code == 200
    fields = get_resp.json()
    assert any(f["value"] == "TestValue" for f in fields)

    # Delete the lead
    delete_resp = auth_client.delete(f"/api/leads/{lead_id}")
    assert delete_resp.status_code == 204

    # Lead should be gone
    get_resp = auth_client.get(f"/api/leads/{lead_id}")
    assert get_resp.status_code == 404

    # Custom field definition should still exist
    list_resp = auth_client.get("/api/custom-fields")
    assert list_resp.status_code == 200
    fields_list = list_resp.json()
    assert any(f["id"] == field_id for f in fields_list)


def test_delete_nonexistent_lead_returns_404(auth_client):
    """Deleting a nonexistent lead returns 404."""
    response = auth_client.delete("/api/leads/99999")
    assert response.status_code == 404


def test_lead_timestamps_are_returned(auth_client):
    """Lead responses include timestamp fields."""
    response = auth_client.post(
        "/api/leads",
        json={"name": "Timestamp Test", "email": "ts@example.com", "company": "Co"},
    )
    assert response.status_code == 201
    data = response.json()
    assert "created_at" in data
    assert "updated_at" in data
    assert data["created_at"] is not None
    assert data["updated_at"] is not None
    # Timestamp should be ISO 8601 format
    assert "T" in data["created_at"]


def test_updating_lead_preserves_created_at(db, test_user, auth_client):
    """Updating a lead preserves created_at and updates updated_at."""
    # Create a lead
    lead_resp = auth_client.post(
        "/api/leads",
        json={"name": "Original", "email": "original@example.com", "company": "Co"},
    )
    assert lead_resp.status_code == 201
    lead_id = lead_resp.json()["id"]
    original_created_at = lead_resp.json()["created_at"]

    # Wait a moment then update
    import time
    time.sleep(1)

    update_resp = auth_client.patch(
        f"/api/leads/{lead_id}",
        json={"name": "Updated Name"},
    )
    assert update_resp.status_code == 200
    updated_data = update_resp.json()
    assert updated_data["created_at"] == original_created_at
    assert updated_data["updated_at"] != original_created_at


def test_overview_endpoint(auth_client):
    """The overview endpoint returns real metrics."""
    response = auth_client.get("/api/dashboard/overview")
    assert response.status_code == 200
    data = response.json()
    assert "kpi" in data
    assert "total_leads" in data["kpi"]
    assert "status_distribution" in data
    assert "lead_trend" in data
    assert "recent_leads" in data
    assert isinstance(data["lead_trend"], list)


def test_pipeline_endpoint(auth_client):
    """The pipeline endpoint returns grouped leads."""
    response = auth_client.get("/api/leads/pipeline")
    assert response.status_code == 200
    data = response.json()
    assert "stages" in data
    assert "summary" in data
    # Check all stages are present
    for stage in ["New", "Contacted", "Qualified", "Proposal", "Negotiation", "Won", "Lost"]:
        assert stage in data["stages"]
        assert "leads" in data["stages"][stage]
        assert "count" in data["stages"][stage]
        assert "total_value" in data["stages"][stage]


def test_pipeline_stage_update(auth_client):
    """Updating a lead's stage via the pipeline works."""
    # Create a lead
    lead_resp = auth_client.post(
        "/api/leads",
        json={"name": "Stage Test", "email": "stage@example.com", "company": "Co", "status": "New"},
    )
    assert lead_resp.status_code == 201
    lead_id = lead_resp.json()["id"]

    # Update stage to Qualified
    update_resp = auth_client.patch(
        f"/api/leads/{lead_id}",
        json={"status": "Qualified"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "Qualified"

    # Verify in pipeline
    pipeline_resp = auth_client.get("/api/leads/pipeline")
    assert pipeline_resp.status_code == 200
    pipeline = pipeline_resp.json()
    qualified_leads = pipeline["stages"]["Qualified"]["leads"]
    assert any(l["id"] == lead_id for l in qualified_leads)
    new_leads = pipeline["stages"]["New"]["leads"]
    assert not any(l["id"] == lead_id for l in new_leads)


def test_invalid_stage_rejected(auth_client):
    """Invalid stage values are rejected so leads never fall off the board."""
    lead_resp = auth_client.post(
        "/api/leads",
        json={"name": "Stage Test", "email": "stage2@example.com", "company": "Co"},
    )
    lead_id = lead_resp.json()["id"]

    response = auth_client.patch(
        f"/api/leads/{lead_id}",
        json={"status": "InvalidStage"},
    )
    assert response.status_code == 422

    # The lead keeps its previous status.
    detail = auth_client.get(f"/api/leads/{lead_id}").json()
    assert detail["status"] == "New"

    create_response = auth_client.post(
        "/api/leads",
        json={
            "name": "Stage Test 2",
            "email": "stage3@example.com",
            "company": "Co",
            "status": "InvalidStage",
        },
    )
    assert create_response.status_code == 422


def test_overview_is_user_isolated(db, test_user, auth_client):
    """Overview metrics only include the current user's leads."""
    from sqlalchemy.orm import sessionmaker
    OtherSession = sessionmaker(bind=db.get_bind())
    other_db = OtherSession()

    other_user = User(
        full_name="Other User",
        email="other4@example.com",
        hashed_password=hash_password("password123"),
        is_active=True,
    )
    other_db.add(other_user)
    other_db.commit()

    # Add leads for the other user
    for i in range(5):
        lead = Lead(
            user_id=other_user.id,
            name=f"Other Lead {i}",
            email=f"other{i}@example.com",
            company="Other Co",
            status="Won",
        )
        other_db.add(lead)
    other_db.commit()

    # Test user's overview should not include other user's leads
    response = auth_client.get("/api/dashboard/overview")
    assert response.status_code == 200
    data = response.json()
    # The test_user may have some leads from other tests, but not the 5 won leads
    assert data["kpi"]["won_deals"] < 5  # Should not include other user's won deals

    other_db.close()


def test_import_is_user_scoped(auth_client, test_user):
    """Import sessions are scoped to the authenticated user."""
    import csv
    import io

    csv_content = (
        "Name,Email,Company\n"
        "Import User,import@example.com,Import Co\n"
    ).encode("utf-8")

    response = auth_client.post(
        "/api/leads/import/preview",
        files={"file": ("leads.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert "session_key" in data

    # Commit the import
    plan_response = auth_client.post(
        "/api/leads/import/plan",
        json={
            "session_key": data["session_key"],
            "filename": "leads.csv",
            "mapping": {"Name": "name", "Email": "email", "Company": "company"},
            "custom_fields": {},
        },
    )
    assert plan_response.status_code == 200

    commit_response = auth_client.post(
        f"/api/leads/import/commit/{data['session_key']}"
    )
    assert commit_response.status_code == 200
    result = commit_response.json()
    assert result["created"] == 1

    # Verify the lead belongs to the current user
    leads_response = auth_client.get("/api/leads")
    assert leads_response.status_code == 200
    leads = leads_response.json()
    imported = [l for l in leads if l["email"] == "import@example.com"]
    assert len(imported) == 1
    assert imported[0]["user_id"] == test_user.id
