import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from bson import ObjectId
from pymongo.database import Database

from app.db.mongo import get_mongo_db


class ReportRepository:
    def __init__(self, db: Optional[Database] = None):
        self.db = db if db is not None else get_mongo_db()
        self.collection = self.db.outreach_reports

    def _format_doc(self, doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not doc:
            return None
        doc = dict(doc)
        doc["id"] = str(doc.get("_id"))
        return doc

    def list_reports(
        self,
        workspace_id: str,
        search: Optional[str] = None,
        is_archived: bool = False,
        sort_by: str = "updated_at",
        sort_order: int = -1,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {
            "workspace_id": workspace_id,
            "is_archived": is_archived,
        }
        if search and search.strip():
            escaped = re.escape(search.strip())
            query["title"] = {"$regex": escaped, "$options": "i"}

        allowed_sorts = {
            "title": "title",
            "created_at": "created_at",
            "updated_at": "updated_at",
            "total_leads": "total_leads",
        }
        sort_field = allowed_sorts.get(sort_by, "updated_at")

        cursor = (
            self.collection.find(query)
            .sort(sort_field, 1 if sort_order == 1 else -1)
            .skip(skip)
            .limit(limit)
        )
        return [self._format_doc(doc) for doc in cursor]

    def count_reports(
        self,
        workspace_id: str,
        search: Optional[str] = None,
        is_archived: bool = False,
    ) -> int:
        query: Dict[str, Any] = {
            "workspace_id": workspace_id,
            "is_archived": is_archived,
        }
        if search and search.strip():
            escaped = re.escape(search.strip())
            query["title"] = {"$regex": escaped, "$options": "i"}
        return self.collection.count_documents(query)

    def get_report(self, workspace_id: str, report_id: str) -> Optional[Dict[str, Any]]:
        # Match string ID or ObjectId
        query: Dict[str, Any] = {"workspace_id": workspace_id}
        if ObjectId.is_valid(report_id):
            query["$or"] = [{"_id": report_id}, {"_id": ObjectId(report_id)}]
        else:
            query["_id"] = report_id

        doc = self.collection.find_one(query)
        return self._format_doc(doc)

    def create_report(
        self,
        workspace_id: str,
        title: str,
        description: str = "",
        created_by: str = "",
        source_file: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        report_id = f"rep_{uuid.uuid4().hex[:12]}"
        doc = {
            "_id": report_id,
            "workspace_id": workspace_id,
            "title": title.strip(),
            "description": description.strip(),
            "created_by": created_by,
            "source_file": source_file,
            "is_archived": False,
            "total_leads": 0,
            "metrics": {
                "total": 0,
                "contacted": 0,
                "not_contacted": 0,
                "interested": 0,
                "not_interested": 0,
                "awaiting_response": 0,
                "follow_up_due": 0,
                "follow_up_overdue": 0,
            },
            "created_at": now,
            "updated_at": now,
        }
        self.collection.insert_one(doc)
        return self._format_doc(doc)

    def update_report(
        self,
        workspace_id: str,
        report_id: str,
        updates: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        query: Dict[str, Any] = {"workspace_id": workspace_id}
        if ObjectId.is_valid(report_id):
            query["$or"] = [{"_id": report_id}, {"_id": ObjectId(report_id)}]
        else:
            query["_id"] = report_id

        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        res = self.collection.find_one_and_update(
            query,
            {"$set": updates},
            return_document=True,
        )
        return self._format_doc(res)

    def delete_report(self, workspace_id: str, report_id: str) -> bool:
        query: Dict[str, Any] = {"workspace_id": workspace_id}
        if ObjectId.is_valid(report_id):
            query["$or"] = [{"_id": report_id}, {"_id": ObjectId(report_id)}]
        else:
            query["_id"] = report_id

        res = self.collection.delete_one(query)
        if res.deleted_count > 0:
            # Delete corresponding leads
            self.db.leads.delete_many({"workspace_id": workspace_id, "report_id": report_id})
            self.db.import_batches.delete_many({"workspace_id": workspace_id, "report_id": report_id})
            return True
        return False

    def recalculate_metrics(self, workspace_id: str, report_id: str) -> Dict[str, Any]:
        match_query = {"workspace_id": workspace_id, "report_id": report_id}
        leads_col = self.db.leads

        total = leads_col.count_documents(match_query)
        contacted = leads_col.count_documents({**match_query, "outcome.contact_status": "contacted"})
        not_contacted = leads_col.count_documents({**match_query, "outcome.contact_status": "not_contacted"})
        interested = leads_col.count_documents({**match_query, "outcome.interest_status": "interested"})
        potentially_interested = leads_col.count_documents({**match_query, "outcome.interest_status": "potentially_interested"})
        not_interested = leads_col.count_documents({**match_query, "outcome.interest_status": "not_interested"})
        awaiting = leads_col.count_documents({**match_query, "outcome.interest_status": "awaiting_response"})
        unclear = leads_col.count_documents({**match_query, "outcome.interest_status": {"$in": ["unclear", "unknown"]}})
        fu_due = leads_col.count_documents({**match_query, "follow_up.status": "due"})
        fu_overdue = leads_col.count_documents({**match_query, "follow_up.status": "overdue"})

        metrics = {
            "total": total,
            "contacted": contacted,
            "not_contacted": not_contacted,
            "interested": interested,
            "potentially_interested": potentially_interested,
            "not_interested": not_interested,
            "awaiting_response": awaiting,
            "unclear": unclear,
            "follow_up_due": fu_due,
            "follow_up_overdue": fu_overdue,
        }

        self.update_report(
            workspace_id,
            report_id,
            {"total_leads": total, "metrics": metrics},
        )
        return metrics
