import re
import uuid
from datetime import datetime, timezone, date
from typing import Any, Dict, List, Optional, Tuple
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database

from app.db.mongo import get_mongo_db


class LeadRepository:
    def __init__(self, db: Optional[Database] = None):
        self.db = db if db is not None else get_mongo_db()
        self.collection = self.db.leads

    def _format_lead(self, doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not doc:
            return None
        doc = dict(doc)
        doc["id"] = str(doc.get("_id"))
        return doc

    def _build_lead_filter(
        self,
        workspace_id: str,
        report_id: Optional[str] = None,
        contact_status: Optional[str] = None,
        interest_status: Optional[str] = None,
        follow_up_status: Optional[str] = None,
        channel: Optional[str] = None,
        employee: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        query: Dict[str, Any] = {"workspace_id": workspace_id}

        if report_id:
            query["report_id"] = report_id

        if contact_status and contact_status.strip() and contact_status != "all":
            query["outcome.contact_status"] = contact_status.strip().lower()

        if interest_status and interest_status.strip() and interest_status != "all":
            query["outcome.interest_status"] = interest_status.strip().lower()

        if follow_up_status and follow_up_status.strip() and follow_up_status != "all":
            query["follow_up.status"] = follow_up_status.strip().lower()

        if channel and channel.strip() and channel != "all":
            query["channel"] = channel.strip().lower()

        if employee and employee.strip() and employee != "all":
            query["assigned_employee"] = employee.strip()

        if search and search.strip():
            escaped = re.escape(search.strip())
            regex = {"$regex": escaped, "$options": "i"}
            query["$or"] = [
                {"normalized.name": regex},
                {"normalized.email": regex},
                {"normalized.phone": regex},
                {"normalized.company": regex},
                {"normalized.location": regex},
                {"attributes.Full Name": regex},
                {"attributes.Company Name": regex},
            ]

        return query

    def find_leads(
        self,
        workspace_id: str,
        report_id: Optional[str] = None,
        contact_status: Optional[str] = None,
        interest_status: Optional[str] = None,
        follow_up_status: Optional[str] = None,
        channel: Optional[str] = None,
        employee: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: int = -1,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        query = self._build_lead_filter(
            workspace_id=workspace_id,
            report_id=report_id,
            contact_status=contact_status,
            interest_status=interest_status,
            follow_up_status=follow_up_status,
            channel=channel,
            employee=employee,
            search=search,
        )

        sort_map = {
            "created_at": "timestamps.created_at",
            "name": "normalized.name",
            "company": "normalized.company",
            "email": "normalized.email",
            "contact_status": "outcome.contact_status",
            "interest_status": "outcome.interest_status",
            "follow_up_date": "follow_up.due_date",
            "follow_up_status": "follow_up.status",
        }
        field = sort_map.get(sort_by, "timestamps.created_at")

        cursor = (
            self.collection.find(query)
            .sort([(field, 1 if sort_order == 1 else -1), ("_id", 1)])
            .skip(skip)
            .limit(limit)
        )
        return [self._format_lead(doc) for doc in cursor]

    def count_leads(
        self,
        workspace_id: str,
        report_id: Optional[str] = None,
        contact_status: Optional[str] = None,
        interest_status: Optional[str] = None,
        follow_up_status: Optional[str] = None,
        channel: Optional[str] = None,
        employee: Optional[str] = None,
        search: Optional[str] = None,
    ) -> int:
        query = self._build_lead_filter(
            workspace_id=workspace_id,
            report_id=report_id,
            contact_status=contact_status,
            interest_status=interest_status,
            follow_up_status=follow_up_status,
            channel=channel,
            employee=employee,
            search=search,
        )
        return self.collection.count_documents(query)

    def get_lead_by_id(self, workspace_id: str, lead_id: str) -> Optional[Dict[str, Any]]:
        query: Dict[str, Any] = {"workspace_id": workspace_id}
        if ObjectId.is_valid(lead_id):
            query["$or"] = [{"_id": lead_id}, {"_id": ObjectId(lead_id)}]
        else:
            try:
                pg_num = int(lead_id)
                query["$or"] = [{"_id": lead_id}, {"pg_id": pg_num}]
            except ValueError:
                query["_id"] = lead_id

        doc = self.collection.find_one(query)
        return self._format_lead(doc)

    def create_lead(self, lead_doc: Dict[str, Any]) -> Dict[str, Any]:
        if "_id" not in lead_doc:
            lead_doc["_id"] = f"lead_{uuid.uuid4().hex[:14]}"
        self.collection.insert_one(lead_doc)
        return self._format_lead(lead_doc)

    def update_lead(
        self,
        workspace_id: str,
        lead_id: str,
        updates: Dict[str, Any],
        actor_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        query: Dict[str, Any] = {"workspace_id": workspace_id}
        if ObjectId.is_valid(lead_id):
            query["$or"] = [{"_id": lead_id}, {"_id": ObjectId(lead_id)}]
        else:
            try:
                pg_num = int(lead_id)
                query["$or"] = [{"_id": lead_id}, {"pg_id": pg_num}]
            except ValueError:
                query["_id"] = lead_id

        now = datetime.now(timezone.utc).isoformat()
        updates["timestamps.updated_at"] = now

        audit_entry = {
            "action": "manual_update",
            "timestamp": now,
            "actor_id": actor_id,
            "updates": {k: v for k, v in updates.items() if not k.startswith("timestamps")},
        }

        res = self.collection.find_one_and_update(
            query,
            {
                "$set": updates,
                "$push": {"history": audit_entry},
            },
            return_document=True,
        )
        return self._format_lead(res)

    def delete_lead(self, workspace_id: str, lead_id: str) -> bool:
        query: Dict[str, Any] = {"workspace_id": workspace_id}
        if ObjectId.is_valid(lead_id):
            query["$or"] = [{"_id": lead_id}, {"_id": ObjectId(lead_id)}]
        else:
            try:
                pg_num = int(lead_id)
                query["$or"] = [{"_id": lead_id}, {"pg_id": pg_num}]
            except ValueError:
                query["_id"] = lead_id

        res = self.collection.delete_one(query)
        return res.deleted_count > 0

    def find_matches_in_report(
        self,
        workspace_id: str,
        report_id: str,
        candidate_ids: List[str],
        candidate_emails: List[str],
        candidate_phones: List[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Return existing leads in this report keyed by id, normalized email, and normalized phone."""
        matches: Dict[str, List[Dict[str, Any]]] = {
            "by_id": {},
            "by_email": {},
            "by_phone": {},
        }
        if not candidate_ids and not candidate_emails and not candidate_phones:
            return matches

        or_conditions = []
        if candidate_ids:
            or_conditions.append({"_id": {"$in": candidate_ids}})
            valid_obj_ids = [ObjectId(i) for i in candidate_ids if ObjectId.is_valid(i)]
            if valid_obj_ids:
                or_conditions.append({"_id": {"$in": valid_obj_ids}})
            pg_ints = []
            for i in candidate_ids:
                try:
                    pg_ints.append(int(i))
                except ValueError:
                    pass
            if pg_ints:
                or_conditions.append({"pg_id": {"$in": pg_ints}})

        clean_emails = [e.lower().strip() for e in candidate_emails if e and e.strip()]
        if clean_emails:
            or_conditions.append({"normalized.email": {"$in": clean_emails}})

        clean_phones = [p.strip() for p in candidate_phones if p and p.strip()]
        if clean_phones:
            or_conditions.append({"normalized.phone": {"$in": clean_phones}})

        if not or_conditions:
            return matches

        cursor = self.collection.find({
            "workspace_id": workspace_id,
            "report_id": report_id,
            "$or": or_conditions,
        })

        for doc in cursor:
            lead = self._format_lead(doc)
            lid = str(lead["id"])
            matches["by_id"].setdefault(lid, []).append(lead)
            if "pg_id" in lead and lead["pg_id"]:
                matches["by_id"].setdefault(str(lead["pg_id"]), []).append(lead)

            norm_email = (lead.get("normalized") or {}).get("email")
            if norm_email:
                matches["by_email"].setdefault(norm_email.lower().strip(), []).append(lead)

            norm_phone = (lead.get("normalized") or {}).get("phone")
            if norm_phone:
                matches["by_phone"].setdefault(norm_phone.strip(), []).append(lead)

        return matches

    def get_follow_up_queue(
        self,
        workspace_id: str,
        category: str = "due_today",
        report_id: Optional[str] = None,
        employee: Optional[str] = None,
        channel: Optional[str] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        today_str = datetime.now(timezone.utc).date().isoformat()
        and_conditions = [{"workspace_id": workspace_id}]

        if report_id and report_id != "all":
            and_conditions.append({"report_id": report_id})
        if employee and employee != "all":
            and_conditions.append({"assigned_employee": employee})
        if channel and channel != "all":
            and_conditions.append({"channel": channel})

        # Category logic — build as OR condition within a stage
        if category == "due_today":
            and_conditions.append({
                "follow_up.status": {"$in": ["due", "scheduled"]},
                "follow_up.due_date": today_str,
            })
        elif category == "overdue":
            and_conditions.append({
                "$or": [
                    {"follow_up.status": "overdue"},
                    {
                        "follow_up.status": {"$in": ["due", "scheduled"]},
                        "follow_up.due_date": {"$lt": today_str},
                    },
                ]
            })
        elif category == "suggested":
            and_conditions.append({"follow_up.status": "suggested"})
        elif category == "awaiting_response":
            and_conditions.append({"outcome.interest_status": "awaiting_response"})
        elif category == "uncontacted":
            and_conditions.append({"outcome.contact_status": "not_contacted"})
            # Ensure contact detail is available
            and_conditions.append({
                "$or": [
                    {"normalized.phone": {"$ne": None, "$exists": True}},
                    {"normalized.email": {"$ne": None, "$exists": True}},
                ]
            })
        elif category == "review_required":
            and_conditions.append({
                "$or": [
                    {"outcome.interest_status": {"$in": ["unclear", "unknown"]}},
                    {"has_conflict": True},
                ]
            })
        elif category == "completed":
            and_conditions.append({"follow_up.status": "completed"})
        # else "all": return all follow ups

        # Add search as an OR within the AND chain
        if search and search.strip():
            escaped = re.escape(search.strip())
            regex = {"$regex": escaped, "$options": "i"}
            and_conditions.append({
                "$or": [
                    {"normalized.name": regex},
                    {"normalized.email": regex},
                    {"normalized.phone": regex},
                    {"normalized.company": regex},
                ]
            })

        base_query = {"$and": and_conditions} if len(and_conditions) > 1 else and_conditions[0]

        cursor = (
            self.collection.find(base_query)
            .sort([("follow_up.due_date", 1), ("timestamps.updated_at", -1)])
            .skip(skip)
            .limit(limit)
        )
        return [self._format_lead(doc) for doc in cursor]

    def count_follow_up_queue(
        self,
        workspace_id: str,
        category: str = "due_today",
        report_id: Optional[str] = None,
        employee: Optional[str] = None,
        channel: Optional[str] = None,
        search: Optional[str] = None,
    ) -> int:
        today_str = datetime.now(timezone.utc).date().isoformat()
        and_conditions = [{"workspace_id": workspace_id}]

        if report_id and report_id != "all":
            and_conditions.append({"report_id": report_id})
        if employee and employee != "all":
            and_conditions.append({"assigned_employee": employee})
        if channel and channel != "all":
            and_conditions.append({"channel": channel})

        # Category logic
        if category == "due_today":
            and_conditions.append({
                "follow_up.status": {"$in": ["due", "scheduled"]},
                "follow_up.due_date": today_str,
            })
        elif category == "overdue":
            and_conditions.append({
                "$or": [
                    {"follow_up.status": "overdue"},
                    {
                        "follow_up.status": {"$in": ["due", "scheduled"]},
                        "follow_up.due_date": {"$lt": today_str},
                    },
                ]
            })
        elif category == "suggested":
            and_conditions.append({"follow_up.status": "suggested"})
        elif category == "awaiting_response":
            and_conditions.append({"outcome.interest_status": "awaiting_response"})
        elif category == "uncontacted":
            and_conditions.append({"outcome.contact_status": "not_contacted"})
            and_conditions.append({
                "$or": [
                    {"normalized.phone": {"$ne": None, "$exists": True}},
                    {"normalized.email": {"$ne": None, "$exists": True}},
                ]
            })
        elif category == "review_required":
            and_conditions.append({
                "$or": [
                    {"outcome.interest_status": {"$in": ["unclear", "unknown"]}},
                    {"has_conflict": True},
                ]
            })
        elif category == "completed":
            and_conditions.append({"follow_up.status": "completed"})

        # Add search as an OR within the AND chain
        if search and search.strip():
            escaped = re.escape(search.strip())
            regex = {"$regex": escaped, "$options": "i"}
            and_conditions.append({
                "$or": [
                    {"normalized.name": regex},
                    {"normalized.email": regex},
                    {"normalized.phone": regex},
                    {"normalized.company": regex},
                ]
            })

        base_query = {"$and": and_conditions} if len(and_conditions) > 1 else and_conditions[0]
        return self.collection.count_documents(base_query)

    def get_workspace_metrics(self, workspace_id: str) -> Dict[str, Any]:
        match_query = {"workspace_id": workspace_id}
        total_leads = self.collection.count_documents(match_query)
        contacted = self.collection.count_documents({**match_query, "outcome.contact_status": "contacted"})
        not_contacted = self.collection.count_documents({**match_query, "outcome.contact_status": "not_contacted"})
        interested = self.collection.count_documents({**match_query, "outcome.interest_status": "interested"})
        potentially_interested = self.collection.count_documents({**match_query, "outcome.interest_status": "potentially_interested"})
        not_interested = self.collection.count_documents({**match_query, "outcome.interest_status": "not_interested"})
        awaiting_response = self.collection.count_documents({**match_query, "outcome.interest_status": "awaiting_response"})

        today_str = datetime.now(timezone.utc).date().isoformat()
        fu_due = self.collection.count_documents({
            **match_query,
            "follow_up.status": {"$in": ["due", "scheduled"]},
            "follow_up.due_date": today_str,
        })
        fu_overdue = self.collection.count_documents({
            **match_query,
            "$or": [
                {"follow_up.status": "overdue"},
                {
                    "follow_up.status": {"$in": ["due", "scheduled"]},
                    "follow_up.due_date": {"$lt": today_str},
                },
            ],
        })

        # Count distinct non-archived reports
        total_reports = self.db.outreach_reports.count_documents({"workspace_id": workspace_id, "is_archived": False})

        # Recent reports
        recent_reports = list(
            self.db.outreach_reports.find({"workspace_id": workspace_id, "is_archived": False})
            .sort("updated_at", -1)
            .limit(5)
        )
        formatted_reports = []
        for r in recent_reports:
            r["id"] = str(r["_id"])
            formatted_reports.append(r)

        return {
            "total_reports": total_reports,
            "total_leads": total_leads,
            "total_contacted": contacted,
            "total_not_contacted": not_contacted,
            "total_interested": interested,
            "total_potentially_interested": potentially_interested,
            "total_not_interested": not_interested,
            "total_awaiting_response": awaiting_response,
            "follow_ups_due": fu_due,
            "follow_ups_overdue": fu_overdue,
            "recent_reports": formatted_reports,
        }
