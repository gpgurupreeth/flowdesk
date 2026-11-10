
import os

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.auth import router as auth_router
from app.api.routes.custom_fields import router as custom_fields_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.lead_custom_fields import router as lead_custom_fields_router
from app.api.routes.leads import router as leads_router
from app.api.routes.lead_import import router as lead_import_router

from app.api.v1.reports import router as v1_reports_router
from app.api.v1.leads import router as v1_leads_router
from app.api.v1.follow_ups import router as v1_follow_ups_router
from app.api.v1.dashboard import router as v1_dashboard_router
from app.api.v1.export import router as v1_export_router
from app.db.mongo import ensure_indexes
from app.middleware.rate_limit import auth_rate_limiter, rate_limit_middleware
from app.services.auth import ALGORITHM, configure_auth

# Read auth configuration from environment at startup.
_secret_key = os.getenv("AUTH_SECRET_KEY")
_algorithm = os.getenv("AUTH_ALGORITHM", ALGORITHM)
_expire_minutes = int(os.getenv("AUTH_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

configure_auth(
    secret_key=_secret_key or "",
    algorithm=_algorithm,
    access_token_expire_minutes=_expire_minutes,
    refresh_token_expire_days=int(
        os.getenv("AUTH_REFRESH_TOKEN_EXPIRE_DAYS", "7")
    ),
)

if not _secret_key:
    raise RuntimeError(
        "AUTH_SECRET_KEY environment variable is required. "
        "Set it in backend/.env (see .env.example)."
    )

app = FastAPI(title="FlowDesk API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def rate_limit_middleware_wrapper(request: Request, call_next):
    return await rate_limit_middleware(request, call_next)


@app.on_event("startup")
def on_startup():
    try:
        ensure_indexes()
    except Exception as exc:
        print(f"Warning: MongoDB index check deferred: {exc}")


# Legacy API routes (preserved for existing tests and components)
app.include_router(auth_router)
app.include_router(leads_router)
app.include_router(dashboard_router)
app.include_router(lead_import_router)
app.include_router(custom_fields_router)
app.include_router(lead_custom_fields_router)

# V1 Enterprise API routes (backed by MongoDB flexible model)
app.include_router(v1_reports_router)
app.include_router(v1_leads_router)
app.include_router(v1_follow_ups_router)
app.include_router(v1_dashboard_router)
app.include_router(v1_export_router)


@app.get("/health")
def health_check():
    return {"status": "healthy", "version": "2.0.0"}
