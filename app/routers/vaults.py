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
from app.schemas import VaultOut, VaultDetailOut
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
