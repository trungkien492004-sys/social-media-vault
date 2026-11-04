import asyncio
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Vault
from app.schemas import ExtractRequest, TaskResponse
from app.task_manager import task_manager
from app.extractor import detect_platform, sanitize_folder_name, normalize_url
from app.config import settings

router = APIRouter(prefix="/api/tasks", tags=["Tasks"])

@router.post("/start", response_model=TaskResponse)
async def start_task(req: ExtractRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    url = normalize_url(req.url)

    platform = detect_platform(url)
    clean_name = sanitize_folder_name(req.custom_name)

    # Pre-create Vault entry to get ID
    dummy_folder = f"{clean_name}_{platform}_temp"
    vault = Vault(
        custom_name=req.custom_name.strip(),
        platform=platform,
        profile_url=url,
        notes=req.notes.strip() if req.notes else None,
        media_type_filter=req.media_type,
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

    task_id = task_manager.create_task()

    # Dispatch extraction in background
    asyncio.create_task(
        task_manager.run_extraction_task(
            task_id=task_id,
            vault_id=vault.id,
            url=url,
            custom_name=req.custom_name,
            notes=req.notes,
            media_type=req.media_type,
            max_items=req.max_items or 50
        )
    )

    return TaskResponse(
        task_id=task_id,
        vault_id=vault.id,
        status="pending",
        message="Tiến trình đã được kích hoạt thành công"
    )

@router.get("/{task_id}/stream")
async def stream_task_events(task_id: str):
    """
    Server-Sent Events (SSE) endpoint to receive live download progress
    Native StreamingResponse with no-buffer headers for cloud proxies
    """
    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no"
    }
    return StreamingResponse(
        task_manager.event_generator(task_id),
        headers=headers,
        media_type="text/event-stream"
    )

@router.get("/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in task_manager.tasks:
        raise HTTPException(status_code=404, detail="Không tìm thấy thông tin task")
    return task_manager.tasks[task_id]
