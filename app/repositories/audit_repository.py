import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pymongo.database import Database

from app.db.mongo import get_mongo_db


class AuditRepository:
    def __init__(self, db: Optional[Database] = None):
        self.db = db if db is not None else get_mongo_db()
        self.collection = self.db.audit_events

    def log_event(
        self,
        workspace_id: str,
        entity_type: str,
        entity_id: str,
        action: str,
        actor_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        doc = {
            "_id": event_id,
            "workspace_id": workspace_id,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "action": action,
            "actor_id": actor_id,
            "details": details or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.collection.insert_one(doc)
        doc["id"] = event_id
        return doc

    def list_events(
        self,
        workspace_id: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"workspace_id": workspace_id}
        if entity_type:
            query["entity_type"] = entity_type
        if entity_id:
            query["entity_id"] = str(entity_id)

        cursor = self.collection.find(query).sort("timestamp", -1).limit(limit)
        results = []
        for doc in cursor:
            doc["id"] = str(doc.get("_id"))
            results.append(doc)
        return results
