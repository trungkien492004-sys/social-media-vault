import asyncio
import os
import shutil
import zipfile
import tempfile
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app.auth import get_current_user
from app.database import get_db
from app.models import User, Vault, MediaItem
from app.schemas import VaultOut, VaultDetailOut, TaskResponse
from app.task_manager import task_manager
from app.config import settings
from app import storage
import httpx

router = APIRouter(prefix="/api/vaults", tags=["Vaults"])


def get_owned_vault(db: Session, vault_id: int, user: User) -> Vault:
    """Return the vault if it belongs to the user (admins may open any vault)."""
    vault = db.query(Vault).filter(Vault.id == vault_id).first()
    if not vault or (vault.user_id != user.id and not user.is_admin):
        raise HTTPException(status_code=404, detail="Không tìm thấy kho lưu trữ")
    return vault

@router.get("/stats")
def get_vault_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    def agg(col):
        return db.query(col).filter(Vault.user_id == user.id).scalar() or 0
    total_vaults = agg(func.count(Vault.id))
    total_items = agg(func.sum(Vault.total_items))
    total_images = agg(func.sum(Vault.total_images))
    total_videos = agg(func.sum(Vault.total_videos))
    total_bytes = agg(func.sum(Vault.total_size_bytes))
    
    return {
        "total_vaults": total_vaults,
        "total_items": total_items,
        "total_images": total_images,
        "total_videos": total_videos,
        "total_size_bytes": total_bytes,
        "quota_bytes": 0 if (user.is_admin or settings.USER_QUOTA_MB <= 0) else settings.USER_QUOTA_MB * 1024 * 1024
    }

@router.get("", response_model=List[VaultOut])
def list_vaults(
    search: Optional[str] = None,
    platform: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    query = db.query(Vault).filter(Vault.user_id == user.id)
    if platform and platform != "all":
        query = query.filter(Vault.platform == platform.lower())
    
    if search:
        search_filter = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Vault.custom_name.ilike(search_filter),
                Vault.notes.ilike(search_filter),
                Vault.profile_url.ilike(search_filter)
            )
        )
    
    vaults = query.order_by(Vault.created_at.desc()).offset(offset).limit(limit).all()
    return vaults

@router.get("/history")
def link_history(
    limit: int = Query(40, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Distinct links this user has submitted before (newest first), so they never have to search again."""
    rows = (
        db.query(Vault)
        .filter(Vault.user_id == user.id)
        .order_by(Vault.created_at.desc())
        .limit(500)
        .all()
    )
    seen = {}
    for v in rows:
        if v.profile_url.startswith("source://"):
            continue
        entry = seen.get(v.profile_url)
        if entry is None:
            seen[v.profile_url] = {
                "url": v.profile_url,
                "custom_name": v.custom_name,
                "platform": v.platform,
                "status": v.status,
                "vault_id": v.id,
                "last_at": v.created_at.isoformat(),
                "times": 1,
            }
        else:
            entry["times"] += 1
    return list(seen.values())[:limit]


@router.post("/{vault_id}/retry", response_model=TaskResponse)
async def retry_vault(
    vault_id: int,
    max_items: int = Query(50, ge=1, le=150),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Run the extraction again for a vault that failed or got stuck. Previous partial files are cleared first."""
    vault = get_owned_vault(db, vault_id, user)
    if vault.user_id != user.id:
        raise HTTPException(status_code=403, detail="Chỉ chủ kho mới được tải lại")
    if vault.profile_url.startswith("source://"):
        raise HTTPException(status_code=400, detail="Kho tạo từ mã nguồn trang không tải lại được. Hãy dán lại mã nguồn mới (link video hết hạn sau vài giờ).")
    if vault.id in task_manager.active_vaults:
        raise HTTPException(status_code=409, detail="Kho này đang được xử lý, vui lòng đợi")

    # Remove whatever the failed run left behind
    vault_dir = settings.VAULT_DIR / vault.folder_name
    if vault_dir.is_dir():
        shutil.rmtree(vault_dir, ignore_errors=True)
    if storage.enabled():
        storage.delete_keys([m.file_path for m in vault.media_items if m.file_url])
    for m in list(vault.media_items):
        db.delete(m)

    vault.status = "pending"
    vault.error_message = None
    vault.total_items = vault.total_images = vault.total_videos = 0
    vault.total_size_bytes = 0
    db.commit()

    task_id = task_manager.create_task(user.id)
    asyncio.create_task(
        task_manager.run_extraction_task(
            task_id=task_id,
            vault_id=vault.id,
            user_id=user.id,
            url=vault.profile_url,
            custom_name=vault.custom_name,
            notes=vault.notes,
            media_type=vault.media_type_filter or "all",
            max_items=max_items
        )
    )
    return TaskResponse(task_id=task_id, vault_id=vault.id, status="pending", message="Đã bắt đầu tải lại")


@router.get("/{vault_id}", response_model=VaultDetailOut)
def get_vault_detail(vault_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return get_owned_vault(db, vault_id, user)

@router.delete("/{vault_id}")
def delete_vault(vault_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    vault = get_owned_vault(db, vault_id, user)

    # Clean up directory on disk
    vault_dir = settings.VAULT_DIR / vault.folder_name
    if vault_dir.exists() and vault_dir.is_dir():
        try:
            shutil.rmtree(vault_dir)
        except Exception as e:
            pass

    # Remove files from persistent storage too
    if storage.enabled():
        storage.delete_keys([m.file_path for m in vault.media_items if m.file_url])

    db.delete(vault)
    db.commit()
    return {"status": "success", "message": f"Đã xóa kho lưu trữ '{vault.custom_name}'"}

def remove_temp_file(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

@router.get("/{vault_id}/download-zip")
def download_vault_zip(vault_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    vault = get_owned_vault(db, vault_id, user)

    # Create temporary zip file
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    temp_zip_path = temp_zip.name
    temp_zip.close()

    added = 0
    try:
        with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for item in vault.media_items:
                local = settings.VAULT_DIR / item.file_path
                if local.exists():
                    zip_file.write(local, arcname=item.file_name)
                    added += 1
                elif item.file_url:
                    # File lives in persistent storage: stream it into the archive
                    with httpx.stream("GET", item.file_url, timeout=120.0, follow_redirects=True) as resp:
                        if resp.status_code == 200:
                            with zip_file.open(item.file_name, "w", force_zip64=True) as dest:
                                for chunk in resp.iter_bytes(1024 * 256):
                                    dest.write(chunk)
                            added += 1
    except Exception as e:
        remove_temp_file(temp_zip_path)
        raise HTTPException(status_code=500, detail=f"Lỗi khi nén tệp ZIP: {str(e)}")

    if added == 0:
        remove_temp_file(temp_zip_path)
        raise HTTPException(status_code=404, detail="Không có tệp media nào để nén")

    background_tasks.add_task(remove_temp_file, temp_zip_path)
    safe_filename = f"{vault.folder_name}.zip"

    return FileResponse(
        temp_zip_path,
        media_type="application/zip",
        filename=safe_filename
    )
