import os
import shutil
import zipfile
import tempfile
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app.database import get_db
from app.models import Vault, MediaItem
from app.schemas import VaultOut, VaultDetailOut
from app.config import settings

router = APIRouter(prefix="/api/vaults", tags=["Vaults"])

@router.get("/stats")
def get_vault_stats(db: Session = Depends(get_db)):
    total_vaults = db.query(func.count(Vault.id)).scalar() or 0
    total_items = db.query(func.sum(Vault.total_items)).scalar() or 0
    total_images = db.query(func.sum(Vault.total_images)).scalar() or 0
    total_videos = db.query(func.sum(Vault.total_videos)).scalar() or 0
    total_bytes = db.query(func.sum(Vault.total_size_bytes)).scalar() or 0
    
    return {
        "total_vaults": total_vaults,
        "total_items": total_items,
        "total_images": total_images,
        "total_videos": total_videos,
        "total_size_bytes": total_bytes
    }

@router.get("", response_model=List[VaultOut])
def list_vaults(
    search: Optional[str] = None,
    platform: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    query = db.query(Vault)
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
def get_vault_detail(vault_id: int, db: Session = Depends(get_db)):
    vault = db.query(Vault).filter(Vault.id == vault_id).first()
    if not vault:
        raise HTTPException(status_code=404, detail="Không tìm thấy kho lưu trữ")
    return vault

@router.delete("/{vault_id}")
def delete_vault(vault_id: int, db: Session = Depends(get_db)):
    vault = db.query(Vault).filter(Vault.id == vault_id).first()
    if not vault:
        raise HTTPException(status_code=404, detail="Không tìm thấy kho lưu trữ")

    # Clean up directory on disk
    vault_dir = settings.VAULT_DIR / vault.folder_name
    if vault_dir.exists() and vault_dir.is_dir():
        try:
            shutil.rmtree(vault_dir)
        except Exception as e:
            pass

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
def download_vault_zip(vault_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    vault = db.query(Vault).filter(Vault.id == vault_id).first()
    if not vault:
        raise HTTPException(status_code=404, detail="Không tìm thấy kho lưu trữ")

    vault_dir = settings.VAULT_DIR / vault.folder_name
    if not vault_dir.exists() or not vault_dir.is_dir():
        raise HTTPException(status_code=404, detail="Thư mục dữ liệu media không tồn tại trên hệ thống")

    # Create temporary zip file
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    temp_zip_path = temp_zip.name
    temp_zip.close()

    try:
        with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for root, dirs, files in os.walk(vault_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, vault_dir)
                    zip_file.write(file_path, arcname=arcname)
    except Exception as e:
        remove_temp_file(temp_zip_path)
        raise HTTPException(status_code=500, detail=f"Lỗi khi nén tệp ZIP: {str(e)}")

    background_tasks.add_task(remove_temp_file, temp_zip_path)
    safe_filename = f"{vault.folder_name}.zip"

    return FileResponse(
        temp_zip_path,
        media_type="application/zip",
        filename=safe_filename
    )
