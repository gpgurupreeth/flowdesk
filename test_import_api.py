
"""API integration tests for the import workflow and custom fields.

Tests use the FastAPI TestClient against a dedicated test database.
All requests include authentication via the auth_client fixture.
"""

from fastapi.testclient import TestClient

from app.main import app


def _post_preview(client, csv_content: bytes, filename: str = "leads.csv"):
    return client.post(
        "/api/leads/import/preview",
        files={"file": (filename, csv_content, "text/csv")},
    )


def _post_plan(client, session_key: str, mapping: dict, custom_fields: dict = None):
    return client.post(
        "/api/leads/import/plan",
        json={
            "session_key": session_key,
            "filename": "leads.csv",
            "mapping": mapping,
            "custom_fields": custom_fields or {},
        },
    )


def test_preview_returns_session_and_mapping(auth_client):
    csv_content = b"Name,Email,Company\nRahul,rahul@example.com,Acme\n"
    response = _post_preview(auth_client, csv_content)
    assert response.status_code == 200
    data = response.json()
    assert data["total_rows"] == 1
    assert data["headers"] == ["Name", "Email", "Company"]
    assert data["suggested_mapping"]["Name"] == "name"
    assert data["suggested_mapping"]["Email"] == "email"
    assert data["suggested_mapping"]["Company"] == "company"
    assert "session_key" in data
    assert data["ready_for_mapping"] is True


def test_preview_rejects_unsupported_file(auth_client):
    response = auth_client.post(
        "/api/leads/import/preview",
        files={"file": ("leads.pdf", b"not a spreadsheet", "application/pdf")},
    )
    assert response.status_code == 400


def test_preview_rejects_empty_file(auth_client):
    response = auth_client.post(
        "/api/leads/import/preview",
        files={"file": ("leads.csv", b"", "text/csv")},
    )
    assert response.status_code == 400


def test_preview_rejects_duplicate_headers(auth_client):
    csv_content = b"Email,email\na@example.com,b@example.com\n"
    response = _post_preview(auth_client, csv_content)
    assert response.status_code == 400


def test_plan_detects_duplicate_emails_within_file(auth_client):
    csv_content = (
        b"Name,Email,Company\n"
        b"Rahul,rahul@example.com,Acme\n"
        b"Rahul 2,RAHUL@example.com,Acme\n"
    )
    preview = _post_preview(auth_client, csv_content)
    session_key = preview.json()["session_key"]

    response = _post_plan(
        auth_client,
        session_key,
        {"Name": "name", "Email": "email", "Company": "company"},
    )
    assert response.status_code == 200
    plan = response.json()
    assert plan["summary"]["review"] == 2
    assert plan["summary"]["create"] == 0


def test_plan_creates_new_lead(auth_client):
    csv_content = b"Name,Email,Company\nPriya,priya@example.com,Bright\n"
    preview = _post_preview(auth_client, csv_content)
    session_key = preview.json()["session_key"]

    response = _post_plan(
        auth_client,
        session_key,
        {"Name": "name", "Email": "email", "Company": "company"},
    )
    plan = response.json()
    assert plan["summary"]["create"] == 1


def test_commit_then_idempotent_recommit(auth_client):
    csv_content = b"Name,Email,Company\nApi User,api@example.com,API Co\n"
    preview = _post_preview(auth_client, csv_content)
    session_key = preview.json()["session_key"]

    _post_plan(
        auth_client,
        session_key,
        {"Name": "name", "Email": "email", "Company": "company"},
    )

    commit1 = auth_client.post(f"/api/leads/import/commit/{session_key}")
    assert commit1.status_code == 200
    assert commit1.json()["created"] == 1
    assert commit1.json()["already_committed"] is False

    commit2 = auth_client.post(f"/api/leads/import/commit/{session_key}")
    assert commit2.status_code == 200
    assert commit2.json()["already_committed"] is True
    assert commit2.json()["created"] == 0


def test_commit_nonexistent_session_returns_400(auth_client):
    response = auth_client.post("/api/leads/import/commit/nonexistent-key")
    assert response.status_code == 400


def test_create_and_list_custom_fields(auth_client):
    # Create
    response = auth_client.post(
        "/api/custom-fields",
        json={"name": "Campaign Source", "field_type": "text"},
    )
    assert response.status_code == 201
    field = response.json()
    assert field["name"] == "Campaign Source"
    assert field["field_type"] == "text"
    assert field["is_active"] is True

    # List
    response = auth_client.get("/api/custom-fields")
    assert response.status_code == 200
    fields = response.json()
    assert any(f["name"] == "Campaign Source" for f in fields)


def test_custom_field_reuse_case_insensitive(auth_client):
    auth_client.post(
        "/api/custom-fields",
        json={"name": "Campaign Source", "field_type": "text"},
    )
    response = auth_client.post(
        "/api/custom-fields",
        json={"name": "campaign source", "field_type": "text"},
    )
    assert response.status_code == 201
    assert response.json()["id"]  # same field reused


def test_custom_field_incompatible_type_rejected(auth_client):
    auth_client.post(
        "/api/custom-fields",
        json={"name": "Budget", "field_type": "text"},
    )
    response = auth_client.post(
        "/api/custom-fields",
        json={"name": "Budget", "field_type": "number"},
    )
    assert response.status_code == 409


def test_lead_custom_fields_endpoint(auth_client):
    # Create a lead
    lead_resp = auth_client.post(
        "/api/leads",
        json={"name": "CF Lead", "email": "cfield@example.com", "company": "Co"},
    )
    assert lead_resp.status_code == 201
    lead_id = lead_resp.json()["id"]

    # Create a custom field
    field_resp = auth_client.post(
        "/api/custom-fields",
        json={"name": "Industry", "field_type": "text"},
    )
    field_id = field_resp.json()["id"]

    # Set custom field value
    update_resp = auth_client.put(
        f"/api/leads/{lead_id}/custom-fields/{field_id}",
        json={"value": "Technology"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["value"] == "Technology"

    # Retrieve custom fields for the lead
    get_resp = auth_client.get(f"/api/leads/{lead_id}/custom-fields")
    assert get_resp.status_code == 200
    fields = get_resp.json()
    assert any(f["name"] == "Industry" and f["value"] == "Technology" for f in fields)

    # Lead list should include custom fields
    list_resp = auth_client.get("/api/leads")
    assert list_resp.status_code == 200
    leads = list_resp.json()
    target = next(l for l in leads if l["id"] == lead_id)
    assert any(f["name"] == "Industry" for f in target["custom_fields"])


def test_lead_custom_field_type_validation(auth_client):
    lead_resp = auth_client.post(
        "/api/leads",
        json={"name": "Val Lead", "email": "val@example.com", "company": "Co"},
    )
    assert lead_resp.status_code == 201
    lead_id = lead_resp.json()["id"]

    field_resp = auth_client.post(
        "/api/custom-fields",
        json={"name": "Score", "field_type": "number"},
    )
    field_id = field_resp.json()["id"]

    # Invalid number
    response = auth_client.put(
        f"/api/leads/{lead_id}/custom-fields/{field_id}",
        json={"value": "not-a-number"},
    )
    assert response.status_code == 422

    # Valid number
    response = auth_client.put(
        f"/api/leads/{lead_id}/custom-fields/{field_id}",
        json={"value": "42"},
    )
    assert response.status_code == 200
    assert response.json()["value"] == "42"


def test_missing_lead_returns_404(auth_client):
    response = auth_client.get("/api/leads/99999/custom-fields")
    assert response.status_code == 404

    response = auth_client.put(
        "/api/leads/99999/custom-fields/1",
        json={"value": "x"},
    )
    assert response.status_code == 404


def test_unauthenticated_requests_rejected():
    """Requests without auth should be rejected with 401."""
    client = TestClient(app)
    response = client.get("/api/leads")
    assert response.status_code == 401

    response = client.post("/api/leads", json={
        "name": "Test", "email": "test@example.com", "company": "Co"
    })
    assert response.status_code == 401
