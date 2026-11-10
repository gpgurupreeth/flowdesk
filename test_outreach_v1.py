import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.session import SessionLocal
from app.models.user import User
from app.services.auth import create_access_token, hash_password


@pytest.fixture
def other_user(db):
    session = SessionLocal()
    session.query(User).filter(User.email == "v1_other_test@example.com").delete()
    session.commit()
    user = User(
        full_name="Other User",
        email="v1_other_test@example.com",
        hashed_password=hash_password("password123"),
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    session.close()
    return user


@pytest.fixture
def other_auth_client(other_user):
    token = create_access_token(data={"sub": str(other_user.id)})
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_v1_reports_list(auth_client):
    response = auth_client.get("/api/v1/reports")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)


def test_v1_report_lifecycle(auth_client):
    # 1. Create Report
    create_res = auth_client.post(
        "/api/v1/reports",
        json={"title": "Q4 Outreach Campaign", "description": "Testing outreach results"},
    )
    assert create_res.status_code == 201
    rep_data = create_res.json()
    report_id = rep_data["id"]
    assert rep_data["title"] == "Q4 Outreach Campaign"

    # 2. Get Report
    get_res = auth_client.get(f"/api/v1/reports/{report_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == report_id

    # 3. Update Report
    patch_res = auth_client.patch(
        f"/api/v1/reports/{report_id}",
        json={"title": "Q4 Outreach Campaign - Renamed"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["title"] == "Q4 Outreach Campaign - Renamed"

    # 4. Delete Report
    del_res = auth_client.delete(f"/api/v1/reports/{report_id}")
    assert del_res.status_code == 200

    # 5. Verify deleted
    get_after = auth_client.get(f"/api/v1/reports/{report_id}")
    assert get_after.status_code == 404


def test_v1_spreadsheet_import_and_update_workflow(auth_client):
    # Step 1: Upload first CSV (New Leads with arbitrary columns)
    csv_data_1 = (
        "Full Name,Email,Phone,Company,City,Instagram Handle,Budget,Status\n"
        "Elena Rostova,elena@example.com,+1 555-0101,Rostov Design,Seattle,@elena_design,5000,Contacted\n"
        "Marcus Vance,marcus@example.com,+1 555-0102,Vance Tech,Austin,@marcus_vance,12000,New\n"
    )

    preview_res = auth_client.post(
        "/api/v1/reports/preview",
        files={"file": ("batch_1.csv", csv_data_1.encode("utf-8"), "text/csv")},
    )
    assert preview_res.status_code == 200
    prev_data = preview_res.json()
    batch_id = prev_data["batch_id"]
    assert prev_data["total_rows"] == 2
    assert prev_data["summary"]["create"] == 2

    # Step 2: Commit initial import into new report
    commit_res = auth_client.post(
        "/api/v1/reports/commit",
        json={"batch_id": batch_id, "title": "Design & Tech Prospects"},
    )
    assert commit_res.status_code == 200
    commit_data = commit_res.json()
    report_id = commit_data["report_id"]
    assert commit_data["summary"]["create"] == 2

    # Verify leads created with arbitrary attributes retained
    leads_res = auth_client.get(f"/api/v1/reports/{report_id}/leads")
    assert leads_res.status_code == 200
    leads = leads_res.json()["items"]
    assert len(leads) == 2

    elena = next(l for l in leads if l["normalized"]["email"] == "elena@example.com")
    assert elena["attributes"]["Instagram Handle"] == "@elena_design"
    assert elena["attributes"]["Budget"] == "5000"
    assert elena["outcome"]["contact_status"] == "contacted"

    # Step 3: Upload second CSV updating Elena (status -> Interested, blank budget)
    # Elena has phone blank, but budget is blank -> should preserve existing budget and phone!
    csv_data_2 = (
        "Full Name,Email,Phone,Company,City,Instagram Handle,Budget,Status\n"
        "Elena Rostova,elena@example.com,,Rostov Design,Seattle,@elena_design,,Won\n"
        "Sophie Martin,sophie@example.com,+1 555-0103,Martin Global,Chicago,@sophie_m,8000,Contacted\n"
    )

    preview_res2 = auth_client.post(
        "/api/v1/reports/preview",
        data={"target_report_id": report_id},
        files={"file": ("batch_2.csv", csv_data_2.encode("utf-8"), "text/csv")},
    )
    assert preview_res2.status_code == 200
    prev_data2 = preview_res2.json()
    batch_id_2 = prev_data2["batch_id"]
    assert prev_data2["summary"]["update"] == 1
    assert prev_data2["summary"]["create"] == 1

    # Step 4: Commit update into existing report
    commit_res2 = auth_client.post(
        "/api/v1/reports/commit",
        json={"batch_id": batch_id_2, "target_report_id": report_id},
    )
    assert commit_res2.status_code == 200
    assert commit_res2.json()["summary"]["update"] == 1
    assert commit_res2.json()["summary"]["create"] == 1

    # Verify Elena updated without losing existing phone or budget
    leads_after = auth_client.get(f"/api/v1/reports/{report_id}/leads").json()["items"]
    assert len(leads_after) == 3

    elena_updated = next(l for l in leads_after if l["normalized"]["email"] == "elena@example.com")
    assert elena_updated["outcome"]["interest_status"] == "interested"
    assert elena_updated["normalized"]["phone"] == "+15550101"
    assert elena_updated["attributes"]["Phone"] == "+1 555-0101"
    assert elena_updated["attributes"]["Budget"] == "5000"
    assert len(elena_updated["history"]) >= 2

    # Step 5: Test exports for this report
    csv_res = auth_client.get(f"/api/v1/reports/{report_id}/export?format=csv")
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers["content-type"]
    assert b"Lead ID,Report ID,Name,Email" in csv_res.content

    xlsx_res = auth_client.get(f"/api/v1/reports/{report_id}/export?format=xlsx")
    assert xlsx_res.status_code == 200
    assert "spreadsheetml" in xlsx_res.headers["content-type"]
    assert len(xlsx_res.content) > 100

    # Step 6: Test report dashboard
    dash_res = auth_client.get(f"/api/v1/reports/{report_id}/dashboard")
    assert dash_res.status_code == 200
    dash_data = dash_res.json()
    assert "metrics" in dash_data
    assert "interest_distribution" in dash_data
    assert "contact_distribution" in dash_data

    # Clean up test report
    auth_client.delete(f"/api/v1/reports/{report_id}")


def test_v1_follow_up_queue_and_actions(auth_client):
    queue_res = auth_client.get("/api/v1/follow-ups")
    assert queue_res.status_code == 200
    data = queue_res.json()
    assert "counts_by_category" in data
    assert "due_today" in data["counts_by_category"]
    assert "overdue" in data["counts_by_category"]
    assert "suggested" in data["counts_by_category"]


def test_v1_workspace_isolation(auth_client, other_auth_client):
    # 1. User 1 creates a report
    rep = auth_client.post(
        "/api/v1/reports",
        json={"title": "Confidential User 1 Report"},
    ).json()
    rep_id = rep["id"]

    # 2. Other User tries to get User 1's report -> 404
    unauth_get = other_auth_client.get(f"/api/v1/reports/{rep_id}")
    assert unauth_get.status_code == 404

    # 3. Other User tries to get leads -> 404
    unauth_leads = other_auth_client.get(f"/api/v1/reports/{rep_id}/leads")
    assert unauth_leads.status_code == 404

    # 4. Other User tries to export -> 404
    unauth_export = other_auth_client.get(f"/api/v1/reports/{rep_id}/export")
    assert unauth_export.status_code == 404

    # 5. Clean up
    auth_client.delete(f"/api/v1/reports/{rep_id}")
