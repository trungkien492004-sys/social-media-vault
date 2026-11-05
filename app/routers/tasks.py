import asyncio
import re
import uuid
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from sqlalchemy import func
from app.auth import get_current_user
from app.models import User, Vault
from app.schemas import ExtractRequest, BatchExtractRequest, BatchTaskResponse, TaskResponse, SourceExtractRequest
from app.task_manager import task_manager
from app.extractor import detect_platform, detect_platform_from_html, sanitize_folder_name, normalize_url
from app.config import settings

router = APIRouter(prefix="/api/tasks", tags=["Tasks"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no"
}


def auto_name_from_url(url: str, platform: str) -> str:
    """Build a readable vault name from the link, e.g. tiktok.com/@liyethao -> liyethao."""
    try:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split("/") if p]
        handle = next((p.lstrip("@") for p in parts if p.startswith("@")), None)
        if not handle and parts:
            handle = parts[-1]
        if not handle:
            handle = parsed.netloc
        handle = re.sub(r"[^\w\-]+", "_", handle)[:40]
        return f"{platform}_{handle}" if handle else platform
    except Exception:
        return platform


def check_quota(db: Session, user: User) -> None:
    if user.is_admin or settings.USER_QUOTA_MB <= 0:
        return
    used = db.query(func.coalesce(func.sum(Vault.total_size_bytes), 0)).filter(Vault.user_id == user.id).scalar() or 0
    if used >= settings.USER_QUOTA_MB * 1024 * 1024:
        raise HTTPException(
            status_code=403,
            detail=f"Bạn đã dùng hết dung lượng {settings.USER_QUOTA_MB} MB. Hãy xóa bớt kho cũ trước khi tải thêm."
        )


def create_and_dispatch(
    db: Session,
    user: User,
    url: str,
    custom_name: str,
    notes: Optional[str],
    media_type: str,
    max_items: int,
    source_html: Optional[str] = None
) -> TaskResponse:
    if source_html:
        # Content pasted from the user's logged-in browser: no network scraping of the page itself
        platform = detect_platform_from_html(source_html)
        url = f"source://{platform}/{uuid.uuid4().hex[:10]}"
    else:
        url = normalize_url(url)
        platform = detect_platform(url)
    clean_name = sanitize_folder_name(custom_name)

    # Pre-create Vault entry to get ID
    dummy_folder = f"{clean_name}_{platform}_temp"
    vault = Vault(
        custom_name=custom_name.strip(),
        platform=platform,
        profile_url=url,
        notes=notes.strip() if notes else None,
        user_id=user.id,
        media_type_filter=media_type,
        folder_name=dummy_folder,
        folder_path=str(settings.VAULT_DIR / dummy_folder),
        status="pending"
    )
    db.add(vault)
    db.commit()
    db.refresh(vault)

    # Update folder name with exact vault ID
    folder_name = f"{clean_name}_{platform}_{vault.id}"
    vault.folder_name = folder_name
    vault.folder_path = str(settings.VAULT_DIR / folder_name)
    db.commit()

    task_id = task_manager.create_task(user.id)

    asyncio.create_task(
        task_manager.run_extraction_task(
            task_id=task_id,
            vault_id=vault.id,
            user_id=user.id,
            url=url,
            custom_name=custom_name,
            notes=notes,
            media_type=media_type,
            max_items=max_items,
            source_html=source_html,
            platform_override=platform if source_html else None
        )
    )

    return TaskResponse(
        task_id=task_id,
        vault_id=vault.id,
        status="pending",
        message="Tiến trình đã được kích hoạt thành công"
    )


@router.post("/start", response_model=TaskResponse)
async def start_task(req: ExtractRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    check_quota(db, user)
    return create_and_dispatch(db, user, req.url, req.custom_name, req.notes, req.media_type, req.max_items or 50)


@router.post("/start-batch", response_model=BatchTaskResponse)
async def start_batch(req: BatchExtractRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Start one extraction task per link (multi download). Tasks run up to 3 at a time."""
    urls: List[str] = []
    for raw in req.urls:
        u = raw.strip()
        if u and u not in urls:
            urls.append(u)
    if not urls:
        raise HTTPException(status_code=422, detail="Chưa có liên kết hợp lệ nào")

    check_quota(db, user)
    base = (req.custom_name or "").strip()
    responses: List[TaskResponse] = []
    for idx, raw_url in enumerate(urls, start=1):
        url = normalize_url(raw_url)
        platform = detect_platform(url)
        if base:
            name = f"{base} {idx}" if len(urls) > 1 else base
        else:
            name = auto_name_from_url(url, platform)
        responses.append(create_and_dispatch(db, user, url, name, req.notes, req.media_type, req.max_items or 50))

    return BatchTaskResponse(tasks=responses)


@router.post("/start-source", response_model=TaskResponse)
async def start_from_source(req: SourceExtractRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Download media found in page source the user copied from their own logged-in browser."""
    check_quota(db, user)
    name = (req.custom_name or "").strip() or "Mã nguồn trang"
    return create_and_dispatch(db, user, "", name, req.notes, req.media_type, req.max_items or 50, source_html=req.html)


@router.get("/stream-multi")
async def stream_multiple_tasks(
    ids: str = Query(..., description="Comma separated task ids"),
    user: User = Depends(get_current_user)
):
    """Single SSE connection carrying events for many tasks (avoids the browser's per-host connection limit)."""
    task_ids = [i for i in ids.split(",") if i and task_manager.owners.get(i) == user.id]
    return StreamingResponse(
        task_manager.multi_event_generator(task_ids),
        headers=SSE_HEADERS,
        media_type="text/event-stream"
    )


@router.get("/{task_id}/stream")
async def stream_task_events(task_id: str, user: User = Depends(get_current_user)):
    """
    Server-Sent Events (SSE) endpoint to receive live download progress
    Native StreamingResponse with no-buffer headers for cloud proxies
    """
    if task_manager.owners.get(task_id) != user.id:
        raise HTTPException(status_code=404, detail="Không tìm thấy thông tin task")
    return StreamingResponse(
        task_manager.event_generator(task_id),
        headers=SSE_HEADERS,
        media_type="text/event-stream"
    )


@router.get("/{task_id}")
async def get_task_status(task_id: str, user: User = Depends(get_current_user)):
    if task_id not in task_manager.tasks or task_manager.owners.get(task_id) != user.id:
        raise HTTPException(status_code=404, detail="Không tìm thấy thông tin task")
    return task_manager.tasks[task_id]
