
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import DbSession, get_current_active_user
from app.models.import_session import ImportSession
from app.models.user import User
from app.schemas.import_session import (
    ImportPlanRequest,
    ImportPlanResponse,
)
from app.services.import_service import (
    build_import_plan,
    commit_import,
    create_import_session,
)
from app.utils.column_mapper import (
    REQUIRED_FIELDS,
    CUSTOM_FIELD,
    build_custom_field_configs,
    detect_column_mapping,
)
from app.utils.spreadsheet_parser import parse_spreadsheet

router = APIRouter(prefix="/api/leads/import", tags=["Leads Import"])

MAX_FILE_SIZE = 10 * 1024 * 1024


@router.post("/preview")
async def preview_import(
    file: Annotated[UploadFile, File()],
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Stage A: upload and parse a spreadsheet.

    Parses the file, stores the raw rows server-side in a pending import
    session scoped to the authenticated user. No leads or custom-field
    values are written at this stage.
    """
    filename = file.filename or ""

    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A filename is required.",
        )

    content = await file.read(MAX_FILE_SIZE + 1)

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="The file exceeds the 10 MB limit.",
        )

    try:
        rows = parse_spreadsheet(filename, content)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The spreadsheet contains no data rows.",
        )

    # Persist raw rows server-side so later stages never trust client data.
    session = create_import_session(
        filename=filename,
        raw_rows=rows,
        db=db,
        user_id=current_user.id,
    )

    headers = list(rows[0].keys())

    mapping = detect_column_mapping(headers)
    mapped_fields = {
        field for field in mapping.values() if field is not None
    }

    missing_required_fields = sorted(REQUIRED_FIELDS - mapped_fields)

    # Auto-generate custom field configs for every column mapped to __custom__.
    auto_custom_fields = build_custom_field_configs(headers, mapping)

    return {
        "session_key": session.session_key,
        "filename": filename,
        "total_rows": len(rows),
        "headers": headers,
        "suggested_mapping": mapping,
        "auto_custom_fields": auto_custom_fields,
        "missing_required_fields": missing_required_fields,
        "preview_rows": rows[:5],
        "ready_for_mapping": not missing_required_fields,
        "expires_at": session.expires_at.isoformat(),
    }


@router.post("/plan", response_model=ImportPlanResponse)
def create_import_plan(
    payload: ImportPlanRequest,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Stages B-E: validate mapping, validate rows, match leads, detect conflicts.

    Only matches against leads owned by the authenticated user.
    The client must confirm this session to commit.
    """
    try:
        plan = build_import_plan(
            session_key=payload.session_key,
            request=payload,
            db=db,
            user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return plan


@router.post("/commit/{session_key}")
def commit_import_session(
    session_key: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Stage G: confirm and commit the import transactionally.

    Idempotent: committing a completed session returns the stored result
    without re-importing. Expired or failed sessions cannot be committed.
    Only the session owner may commit.
    """
    try:
        result = commit_import(
            session_key=session_key,
            db=db,
            user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return result
