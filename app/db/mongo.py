import os
from typing import Optional
from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "flowdesk")

_client: Optional[MongoClient] = None


def get_mongo_client() -> MongoClient:
    """Return a singleton MongoClient instance."""
    global _client
    if _client is None:
        _client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            maxPoolSize=50,
            minPoolSize=5,
        )
    return _client


def get_mongo_db(db_name: Optional[str] = None) -> Database:
    """Return the application MongoDB database instance."""
    client = get_mongo_client()
    return client[db_name or MONGODB_DATABASE]


def ensure_indexes(db: Optional[Database] = None) -> None:
    """Create essential performance and uniqueness indexes on all collections."""
    if db is None:
        db = get_mongo_db()

    # Users
    db.users.create_index([("email", ASCENDING)], unique=True)
    db.users.create_index([("workspace_id", ASCENDING)])

    # Workspaces
    db.workspaces.create_index([("owner_id", ASCENDING)])

    # Outreach Reports
    db.outreach_reports.create_index(
        [("workspace_id", ASCENDING), ("is_archived", ASCENDING), ("updated_at", DESCENDING)]
    )
    db.outreach_reports.create_index([("workspace_id", ASCENDING), ("created_at", DESCENDING)])

    # Leads
    db.leads.create_index([("workspace_id", ASCENDING), ("report_id", ASCENDING)])
    db.leads.create_index(
        [("workspace_id", ASCENDING), ("report_id", ASCENDING), ("outcome.contact_status", ASCENDING)]
    )
    db.leads.create_index(
        [("workspace_id", ASCENDING), ("report_id", ASCENDING), ("outcome.interest_status", ASCENDING)]
    )
    db.leads.create_index(
        [("workspace_id", ASCENDING), ("follow_up.status", ASCENDING), ("follow_up.due_date", ASCENDING)]
    )
    db.leads.create_index([("workspace_id", ASCENDING), ("normalized.email", ASCENDING)])
    db.leads.create_index([("workspace_id", ASCENDING), ("normalized.phone", ASCENDING)])
    db.leads.create_index([("report_id", ASCENDING), ("timestamps.created_at", DESCENDING)])

    # Import Batches
    db.import_batches.create_index([("report_id", ASCENDING), ("created_at", DESCENDING)])
    db.import_batches.create_index([("workspace_id", ASCENDING), ("created_at", DESCENDING)])

    # Audit Events
    db.audit_events.create_index([("workspace_id", ASCENDING), ("timestamp", DESCENDING)])
    db.audit_events.create_index([("entity_type", ASCENDING), ("entity_id", ASCENDING)])
