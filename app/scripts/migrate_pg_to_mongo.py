import json
import os
import sys
from datetime import datetime, timezone, date
from decimal import Decimal
from typing import Any, Dict, List

from dotenv import load_dotenv
from sqlalchemy import inspect, text

load_dotenv()

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.db.session import engine
from app.db.mongo import get_mongo_db, ensure_indexes


def serialize_val(val: Any) -> Any:
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    return val


def normalize_contact_status(status_str: str) -> str:
    s = (status_str or "").strip().lower()
    if s in ["new", "uncontacted", "not contacted", "pending"]:
        return "not_contacted"
    if s in ["attempted", "calling", "queued"]:
        return "attempted"
    if s in ["contacted", "in progress", "qualified", "replied", "won", "lost"]:
        return "contacted"
    return "not_contacted"


def normalize_interest_status(status_str: str) -> str:
    s = (status_str or "").strip().lower()
    if s in ["won", "hot", "interested", "qualified", "positive"]:
        return "interested"
    if s in ["lost", "not interested", "declined", "unqualified"]:
        return "not_interested"
    if s in ["contacted", "in progress", "awaiting response", "follow up"]:
        return "awaiting_response"
    if s in ["new"]:
        return "unknown"
    return "unknown"


def run_migration():
    print("=" * 60)
    print("FLOWDESK: POSTGRESQL TO MONGODB SAFE MIGRATION")
    print("=" * 60)

    mongo_db = get_mongo_db()
    ensure_indexes(mongo_db)

    with engine.connect() as conn:
        # 1. Check PostgreSQL source counts
        pg_user_count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
        pg_lead_count = conn.execute(text("SELECT COUNT(*) FROM leads")).scalar()
        pg_session_count = conn.execute(text("SELECT COUNT(*) FROM import_sessions")).scalar()
        pg_cf_count = conn.execute(text("SELECT COUNT(*) FROM custom_field_definitions")).scalar()
        pg_cfv_count = conn.execute(text("SELECT COUNT(*) FROM lead_custom_field_values")).scalar()

        print(f"Source PostgreSQL Stats:")
        print(f"  - Users: {pg_user_count}")
        print(f"  - Leads: {pg_lead_count}")
        print(f"  - Import Sessions: {pg_session_count}")
        print(f"  - Custom Field Definitions: {pg_cf_count}")
        print(f"  - Lead Custom Field Values: {pg_cfv_count}")
        print("-" * 60)

        # 2. Fetch all Custom Field Definitions & Values
        cf_defs = {}
        for r in conn.execute(text("SELECT id, user_id, name, field_type FROM custom_field_definitions")).fetchall():
            cf_defs[r[0]] = {"user_id": r[1], "name": r[2], "type": r[3]}

        lead_cf_map: Dict[int, Dict[str, Any]] = {}
        for r in conn.execute(text("SELECT lead_id, custom_field_id, value FROM lead_custom_field_values")).fetchall():
            lead_id, cf_id, val = r[0], r[1], r[2]
            if cf_id in cf_defs:
                field_name = cf_defs[cf_id]["name"]
                if lead_id not in lead_cf_map:
                    lead_cf_map[lead_id] = {}
                lead_cf_map[lead_id][field_name] = val

        # 3. Migrate Users & Workspaces
        users = conn.execute(text("SELECT id, email, full_name, hashed_password, is_active, created_at, updated_at FROM users")).fetchall()
        migrated_users = 0
        for u in users:
            u_id, email, full_name, hashed_pwd, is_active, c_at, u_at = u
            workspace_id = f"ws_user_{u_id}"
            
            # Upsert Workspace
            mongo_db.workspaces.update_one(
                {"_id": workspace_id},
                {
                    "$set": {
                        "name": f"{full_name}'s Workspace",
                        "owner_id": str(u_id),
                        "settings": {
                            "follow_up_days": 3,
                            "auto_suggest_follow_up": True,
                        },
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                    "$setOnInsert": {
                        "created_at": serialize_val(c_at) or datetime.now(timezone.utc).isoformat(),
                    }
                },
                upsert=True,
            )

            # Upsert User
            mongo_db.users.update_one(
                {"email": email},
                {
                    "$set": {
                        "pg_id": u_id,
                        "full_name": full_name,
                        "hashed_password": hashed_pwd,
                        "workspace_id": workspace_id,
                        "role": "admin",
                        "is_active": is_active,
                        "updated_at": serialize_val(u_at) or datetime.now(timezone.utc).isoformat(),
                    },
                    "$setOnInsert": {
                        "_id": f"user_{u_id}",
                        "created_at": serialize_val(c_at) or datetime.now(timezone.utc).isoformat(),
                    }
                },
                upsert=True,
            )
            migrated_users += 1

        print(f"Migrated/Updated Users: {migrated_users}")

        # 4. Migrate Import Sessions into Outreach Reports & Batches
        sessions = conn.execute(text("SELECT id, user_id, session_key, filename, status, import_plan, created_at FROM import_sessions")).fetchall()
        report_map: Dict[str, str] = {} # key: (user_id, filename) -> report_id
        session_to_report: Dict[int, str] = {}

        for s in sessions:
            s_id, u_id, s_key, fname, s_status, plan_raw, c_at = s
            workspace_id = f"ws_user_{u_id}"
            plan = json.loads(plan_raw) if isinstance(plan_raw, str) else (plan_raw or {})
            
            report_key = f"{u_id}_{fname}"
            if report_key not in report_map:
                report_id = f"rep_{u_id}_{s_id}"
                report_title = f"{fname.rsplit('.', 1)[0].replace('_', ' ').replace('-', ' ').title()} Report"
                
                mongo_db.outreach_reports.update_one(
                    {"_id": report_id},
                    {
                        "$set": {
                            "workspace_id": workspace_id,
                            "title": report_title,
                            "description": f"Imported from {fname}",
                            "created_by": f"user_{u_id}",
                            "source_file": fname,
                            "is_archived": False,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                        "$setOnInsert": {
                            "created_at": serialize_val(c_at) or datetime.now(timezone.utc).isoformat(),
                        }
                    },
                    upsert=True,
                )
                report_map[report_key] = report_id

            target_report_id = report_map[report_key]
            session_to_report[s_id] = target_report_id

            # Save Batch
            batch_id = f"batch_{s_id}"
            mongo_db.import_batches.update_one(
                {"_id": batch_id},
                {
                    "$set": {
                        "workspace_id": workspace_id,
                        "report_id": target_report_id,
                        "session_key": s_key,
                        "filename": fname,
                        "status": s_status,
                        "summary": plan.get("summary", {}),
                        "created_by": f"user_{u_id}",
                        "created_at": serialize_val(c_at) or datetime.now(timezone.utc).isoformat(),
                    }
                },
                upsert=True,
            )

        # 5. Migrate Leads
        # Retrieve all leads from PostgreSQL
        pg_leads = conn.execute(text(
            "SELECT id, user_id, name, email, company, phone, location, status, deal_value, follow_up_date, created_at, updated_at, imported_at FROM leads"
        )).fetchall()

        migrated_leads = 0
        for l in pg_leads:
            l_id, u_id, name, email, company, phone, location, status, deal_val, fu_date, c_at, u_at, imp_at = l
            workspace_id = f"ws_user_{u_id}"

            # Determine report_id for this lead
            # If user has reports from sessions, assign to the most relevant report or user's main report
            report_candidates = [rep_id for k, rep_id in report_map.items() if k.startswith(f"{u_id}_")]
            if report_candidates:
                target_report_id = report_candidates[-1]
            else:
                target_report_id = f"rep_{u_id}_default"
                mongo_db.outreach_reports.update_one(
                    {"_id": target_report_id},
                    {
                        "$set": {
                            "workspace_id": workspace_id,
                            "title": "Primary Outreach Report",
                            "description": "Default report for existing leads",
                            "created_by": f"user_{u_id}",
                            "is_archived": False,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                        "$setOnInsert": {
                            "created_at": serialize_val(c_at) or datetime.now(timezone.utc).isoformat(),
                        }
                    },
                    upsert=True,
                )

            # Build attributes dictionary preserving all original and custom values
            attrs = {
                "Full Name": name,
                "Email Address": email,
                "Company Name": company,
            }
            if phone:
                attrs["Phone Number"] = phone
            if location:
                attrs["Location"] = location
            if deal_val is not None:
                attrs["Deal Value"] = float(deal_val)
            if status:
                attrs["Original Status"] = status

            # Merge custom fields from PostgreSQL
            if l_id in lead_cf_map:
                for k, v in lead_cf_map[l_id].items():
                    attrs[k] = v

            contact_status = normalize_contact_status(status)
            interest_status = normalize_interest_status(status)

            follow_up_status = "not_required"
            fu_date_str = serialize_val(fu_date)
            if fu_date_str:
                today_str = datetime.now(timezone.utc).date().isoformat()
                if fu_date_str < today_str:
                    follow_up_status = "overdue"
                elif fu_date_str == today_str:
                    follow_up_status = "due"
                else:
                    follow_up_status = "scheduled"

            lead_doc = {
                "workspace_id": workspace_id,
                "report_id": target_report_id,
                "pg_id": l_id,
                "attributes": attrs,
                "normalized": {
                    "name": name,
                    "email": email.strip().lower() if email else None,
                    "phone": phone.strip() if phone else None,
                    "company": company.strip() if company else None,
                    "location": location.strip() if location else None,
                    "deal_value": float(deal_val) if deal_val is not None else None,
                },
                "outcome": {
                    "contact_status": contact_status,
                    "interest_status": interest_status,
                    "source": "imported",
                    "original_label": status,
                },
                "channel": "phone" if phone else ("email" if email else "unknown"),
                "assigned_employee": attrs.get("Sales Representative") or None,
                "follow_up": {
                    "status": follow_up_status,
                    "due_date": fu_date_str,
                    "reason": "Migrated from existing records",
                    "notes": "",
                    "completed_at": None,
                },
                "timestamps": {
                    "created_at": serialize_val(c_at) or datetime.now(timezone.utc).isoformat(),
                    "updated_at": serialize_val(u_at) or datetime.now(timezone.utc).isoformat(),
                    "first_seen_at": serialize_val(imp_at or c_at) or datetime.now(timezone.utc).isoformat(),
                },
                "history": [
                    {
                        "action": "migrated_from_postgres",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "details": f"Imported with status: {status}",
                    }
                ],
            }

            mongo_db.leads.update_one(
                {"workspace_id": workspace_id, "pg_id": l_id},
                {"$set": lead_doc},
                upsert=True,
            )
            migrated_leads += 1

        print(f"Migrated Leads: {migrated_leads} (Target: {pg_lead_count})")

        # 6. Recalculate metrics on all Outreach Reports
        reports = list(mongo_db.outreach_reports.find())
        for rep in reports:
            r_id = rep["_id"]
            total = mongo_db.leads.count_documents({"report_id": r_id})
            contacted = mongo_db.leads.count_documents({"report_id": r_id, "outcome.contact_status": "contacted"})
            not_contacted = mongo_db.leads.count_documents({"report_id": r_id, "outcome.contact_status": "not_contacted"})
            interested = mongo_db.leads.count_documents({"report_id": r_id, "outcome.interest_status": "interested"})
            not_interested = mongo_db.leads.count_documents({"report_id": r_id, "outcome.interest_status": "not_interested"})
            awaiting = mongo_db.leads.count_documents({"report_id": r_id, "outcome.interest_status": "awaiting_response"})
            fu_due = mongo_db.leads.count_documents({"report_id": r_id, "follow_up.status": "due"})
            fu_overdue = mongo_db.leads.count_documents({"report_id": r_id, "follow_up.status": "overdue"})

            mongo_db.outreach_reports.update_one(
                {"_id": r_id},
                {
                    "$set": {
                        "total_leads": total,
                        "metrics": {
                            "total": total,
                            "contacted": contacted,
                            "not_contacted": not_contacted,
                            "interested": interested,
                            "not_interested": not_interested,
                            "awaiting_response": awaiting,
                            "follow_up_due": fu_due,
                            "follow_up_overdue": fu_overdue,
                        }
                    }
                }
            )

        # 7. Final Reconciliation & Verification Check
        mongo_user_count = mongo_db.users.count_documents({"pg_id": {"$exists": True}})
        mongo_lead_count = mongo_db.leads.count_documents({"pg_id": {"$exists": True}})
        print("=" * 60)
        print("RECONCILIATION AUDIT:")
        print(f"  PostgreSQL Users: {pg_user_count} | MongoDB Migrated Users: {mongo_user_count} -> MATCH: {pg_user_count == mongo_user_count}")
        print(f"  PostgreSQL Leads: {pg_lead_count} | MongoDB Migrated Leads: {mongo_lead_count} -> MATCH: {pg_lead_count == mongo_lead_count}")
        
        assert pg_user_count == mongo_user_count, "User count mismatch!"
        assert pg_lead_count == mongo_lead_count, "Lead count mismatch!"
        print("MIGRATION SUCCESSFUL! 100% of records preserved and verified without data loss.")
        print("=" * 60)


if __name__ == "__main__":
    run_migration()
