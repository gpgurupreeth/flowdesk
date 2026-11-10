import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from bson import ObjectId
from pymongo.database import Database

from app.db.mongo import get_mongo_db


class BatchRepository:
    def __init__(self, db: Optional[Database] = None):
        self.db = db if db is not None else get_mongo_db()
        self.collection = self.db.import_batches

    def _format_batch(self, doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not doc:
            return None
        doc = dict(doc)
        doc["id"] = str(doc.get("_id"))
        return doc

    def create_batch(
        self,
        workspace_id: str,
        report_id: str,
        filename: str,
        file_size: int,
        created_by: str,
        summary: Optional[Dict[str, Any]] = None,
        status: str = "pending",
        plan: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        batch_id = f"batch_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        doc = {
            "_id": batch_id,
            "workspace_id": workspace_id,
            "report_id": report_id,
            "filename": filename,
            "file_size": file_size,
            "status": status,
            "summary": summary or {},
            "plan": plan or {},
            "created_by": created_by,
            "created_at": now,
            "completed_at": None,
            "errors": [],
            "warnings": [],
        }
        self.collection.insert_one(doc)
        return self._format_batch(doc)

    def get_batch(self, workspace_id: str, batch_id: str) -> Optional[Dict[str, Any]]:
        query: Dict[str, Any] = {"workspace_id": workspace_id}
        if ObjectId.is_valid(batch_id):
            query["$or"] = [{"_id": batch_id}, {"_id": ObjectId(batch_id)}]
        else:
            query["_id"] = batch_id
        doc = self.collection.find_one(query)
        return self._format_batch(doc)

    def list_batches(self, workspace_id: str, report_id: str) -> List[Dict[str, Any]]:
        cursor = (
            self.collection.find({"workspace_id": workspace_id, "report_id": report_id})
            .sort("created_at", -1)
            .limit(50)
        )
        return [self._format_batch(doc) for doc in cursor]

    def update_batch_status(
        self,
        workspace_id: str,
        batch_id: str,
        status: str,
        summary: Optional[Dict[str, Any]] = None,
        errors: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        query: Dict[str, Any] = {"workspace_id": workspace_id}
        if ObjectId.is_valid(batch_id):
            query["$or"] = [{"_id": batch_id}, {"_id": ObjectId(batch_id)}]
        else:
            query["_id"] = batch_id

        updates: Dict[str, Any] = {"status": status}
        if summary is not None:
            updates["summary"] = summary
        if errors is not None:
            updates["errors"] = errors
        if warnings is not None:
            updates["warnings"] = warnings
        if status in ["completed", "failed", "cancelled"]:
            updates["completed_at"] = datetime.now(timezone.utc).isoformat()

        doc = self.collection.find_one_and_update(
            query,
            {"$set": updates},
            return_document=True,
        )
        return self._format_batch(doc)
