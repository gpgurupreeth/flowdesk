
from app.db.base import Base
from app.db.session import engine

# Import every model so SQLAlchemy registers its table.
from app.models.user import User
from app.models.lead import Lead
from app.models.custom_field import CustomFieldDefinition
from app.models.lead_custom_field_value import LeadCustomFieldValue
from app.models.import_session import ImportSession


def init_db():
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_db()
    print("Database tables initialized successfully.")
