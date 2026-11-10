# FlowDesk Backend API

Enterprise CRM platform for managing outreach campaigns, leads, and sales pipelines. Built with FastAPI, MongoDB, and PostgreSQL.

## Overview

FlowDesk backend provides:
- **User Management** - Authentication with JWT tokens and role-based access
- **Lead Management** - Import, normalize, and manage lead data with custom fields
- **Outreach Reports** - Organize leads into campaigns with custom column mapping
- **Follow-up Intelligence** - Intelligent follow-up queue with categorization
- **Data Export** - CSV/XLSX exports with filtering and field selection
- **Audit Logging** - Track all changes to leads and reports

## Tech Stack

- **Framework:** FastAPI 0.162.0
- **Database:** MongoDB (leads, reports) + PostgreSQL (users, optional legacy)
- **Auth:** JWT tokens + bcrypt password hashing
- **Async:** Motor (MongoDB async driver), asyncio
- **Validation:** Pydantic v2 with settings management
- **Migrations:** Alembic (PostgreSQL)

## Prerequisites

- Python 3.10+
- MongoDB 4.4+ (running and accessible)
- PostgreSQL 12+ (optional, for legacy data)
- pip or conda

## Installation

### 1. Clone and Setup Virtual Environment

```bash
cd flowdesk/backend
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # macOS/Linux
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

Copy `.env.example` to `.env` and update:

```bash
cp .env.example .env
```

**Key variables:**
```
MONGODB_URL=mongodb://localhost:27017/flowdesk
POSTGRES_URL=postgresql://user:password@localhost/flowdesk
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
```

### 4. Initialize Database

```bash
# Run Alembic migrations (PostgreSQL)
alembic upgrade head

# MongoDB indexes are created automatically on first run
```

## Running the Server

### Development

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API will be available at `http://127.0.0.1:8000`  
Interactive docs at `http://127.0.0.1:8000/docs`

### Production

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## Project Structure

```
backend/
├── app/
│   ├── api/
│   │   ├── routes/          # API route handlers
│   │   │   ├── auth.py      # Login, register, token refresh
│   │   │   ├── leads.py     # Lead CRUD operations
│   │   │   ├── reports.py   # Report management
│   │   │   └── ...
│   │   ├── v1/              # V1 API endpoints (MongoDB)
│   │   │   ├── leads.py
│   │   │   ├── reports.py
│   │   │   ├── follow_ups.py
│   │   │   └── export.py
│   │   └── deps.py          # Dependency injection (auth, DB)
│   ├── models/              # Pydantic response models
│   ├── repositories/        # Data access layer
│   │   ├── lead_repository.py
│   │   ├── report_repository.py
│   │   └── ...
│   ├── schemas/             # Request/response schemas
│   ├── services/            # Business logic
│   │   ├── auth.py
│   │   ├── import_service.py
│   │   ├── export_service.py
│   │   └── ...
│   ├── db/                  # Database connections
│   │   ├── mongo.py
│   │   ├── session.py
│   │   └── ...
│   ├── middleware/          # Rate limiting, logging
│   └── main.py              # FastAPI app initialization
├── alembic/                 # Database migrations
├── tests/                   # Unit and integration tests
├── requirements.txt         # Python dependencies
└── README.md
```

## API Endpoints

### Authentication

```
POST   /api/auth/register       - Create user account
POST   /api/auth/login          - Get JWT access token
POST   /api/auth/refresh        - Refresh expired token
GET    /api/auth/me             - Get current user
```

### Leads (V1 API - MongoDB)

```
GET    /api/v1/leads                      - List all workspace leads
GET    /api/v1/leads/{lead_id}            - Get lead details
PATCH  /api/v1/leads/{lead_id}/outcome    - Update contact/interest status
PATCH  /api/v1/leads/{lead_id}/follow-up  - Update follow-up status/date
DELETE /api/v1/leads/{lead_id}            - Delete lead record
```

### Reports

```
GET    /api/v1/reports                         - List reports
GET    /api/v1/reports/{report_id}            - Get report details
GET    /api/v1/reports/{report_id}/leads      - List report leads (with filters)
GET    /api/v1/reports/{report_id}/dashboard  - Get report metrics
GET    /api/v1/reports/{report_id}/export     - Export as CSV/XLSX
POST   /api/v1/reports/preview                - Preview spreadsheet import
POST   /api/v1/reports/commit                 - Commit import to database
```

### Follow-up Queue

```
GET    /api/v1/follow-ups                           - Get follow-up queue
PATCH  /api/v1/follow-ups/{lead_id}/complete       - Mark as completed
PATCH  /api/v1/follow-ups/{lead_id}/reschedule     - Change due date
POST   /api/v1/follow-ups/{lead_id}/note           - Add follow-up note
```

## Authentication

All requests (except `/auth/register` and `/auth/login`) require Bearer token:

```
Authorization: Bearer <access_token>
```

Token obtained from `/api/auth/login` response.

## Testing

### Run All Tests

```bash
pytest -v
```

### Run Specific Test Suite

```bash
pytest test_auth.py -v              # Authentication tests
pytest test_import_api.py -v        # Import workflow tests
pytest test_lead_import_matcher.py   # Lead matching logic
```

### Test Coverage

```bash
pytest --cov=app --cov-report=html
```

## Recent Bug Fixes (Phase 1-8)

### Phase 1: Authentication Fix
- Login now properly stores JWT token AND user context
- Prevents "logged out" state after successful login

### Phase 2: Authenticated Exports
- CSV/XLSX exports now require Bearer token authentication
- No more 401 Unauthorized errors on export download

### Phase 3: Follow-up Search Fix
- Fixed MongoDB query builder to combine search + category filters
- Before: search filters were lost when category was specified
- After: Both search AND category filters applied correctly

### Phase 4: Data Consistency
- All APIs use V1 (MongoDB) endpoints exclusively
- PostgreSQL legacy data remains isolated
- Users see consistent data from single source

### Phase 5: Pipeline Read-Only
- Removed crash-causing undefined variables in Pipeline component
- Pipeline now safely displays leads as read-only cards

### Phase 6: Sidebar Layout
- Fixed logout button overflow in sidebar
- Changed flex layout to column direction

### Phase 7: Dependencies
- Added `requirements.txt` with 58 pinned dependencies
- Frontend `chart.js` dependency declared in package.json

### Phase 8: Verification
- 14+ unit tests passing (auth, import, validation)
- Tested against real MongoDB (100k+ leads)
- All critical journeys verified working

See `VERIFICATION_REPORT.md` for detailed test results.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGODB_URL` | `mongodb://localhost:27017/flowdesk` | MongoDB connection string |
| `POSTGRES_URL` | `postgresql://localhost/flowdesk` | PostgreSQL connection (optional) |
| `SECRET_KEY` | (required) | JWT signing secret |
| `ALGORITHM` | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | Token expiry time |
| `ENVIRONMENT` | `development` | `development` or `production` |
| `LOG_LEVEL` | `INFO` | Logging level |

## Troubleshooting

### MongoDB Connection Error

```
Error: Unable to connect to MongoDB at mongodb://localhost:27017
```

**Solution:** Ensure MongoDB is running and URL is correct:
```bash
mongosh  # Verify connection
```

### Import Preview Fails

```
File format not supported. Supported: .xlsx, .csv, .xls
```

**Solution:** Ensure file is valid Excel or CSV with proper headers.

### Follow-up Search Returns No Results

**Solution:** Verify both category AND search filters are applied. Test with:
```bash
curl -H "Authorization: Bearer TOKEN" \
  "http://localhost:8000/api/v1/follow-ups?category=overdue&search=test"
```

### Tests Timeout

**Solution:** Full test suite takes 2-5 minutes. Run specific tests instead:
```bash
pytest test_auth.py -v  # ~12 seconds
```

## Performance Notes

- MongoDB indexes on `workspace_id`, `report_id`, `created_at` are critical
- Follow-up queue filter with search on 100k+ leads: ~500ms
- Export generation time depends on file format and record count
- JWT token refresh uses in-memory cache for speed

## Security

- Passwords hashed with bcrypt (10 rounds)
- JWT tokens signed with SECRET_KEY (keep it secret!)
- All database queries parameterized (no SQL injection)
- CORS configured for frontend origin only
- Rate limiting on auth endpoints (10 requests/min)

## Database Schema

### MongoDB Collections

- **leads** - Lead records with normalized data, outcomes, follow-ups
- **reports** - Campaign/report metadata and metrics
- **custom_fields** - Workspace-specific field definitions
- **import_sessions** - Temporary state during spreadsheet import

### PostgreSQL Tables

- **users** - User accounts and authentication
- **workspaces** - Team workspaces (optional)

## Contributing

1. Run tests: `pytest`
2. Follow PEP 8 style guide
3. Add tests for new features
4. Update this README for API changes

## License

Proprietary - FlowDesk

## Support

For issues or questions, contact the development team or check `VERIFICATION_REPORT.md` for known limitations.
