import shutil
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import storage
from app.auth import require_admin
from app.config import settings
from app.database import get_db
from app.models import AppSetting, MediaItem, User, Vault
from app.schemas import AdminUserOut, VaultOut

router = APIRouter(prefix="/api/admin", tags=["Admin"])


@router.get("/overview")
def overview(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {
        "users": db.query(func.count(User.id)).scalar() or 0,
        "vaults": db.query(func.count(Vault.id)).scalar() or 0,
        "items": db.query(func.coalesce(func.sum(Vault.total_items), 0)).scalar() or 0,
        "size_bytes": db.query(func.coalesce(func.sum(Vault.total_size_bytes), 0)).scalar() or 0,
    }


@router.get("/users", response_model=List[AdminUserOut])
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = (
        db.query(
            User,
            func.count(Vault.id),
            func.coalesce(func.sum(Vault.total_items), 0),
            func.coalesce(func.sum(Vault.total_size_bytes), 0),
        )
        .outerjoin(Vault, Vault.user_id == User.id)
        .group_by(User.id)
        .order_by(User.created_at.desc())
        .all()
    )
    return [
        AdminUserOut(
            id=u.id, email=u.email, is_admin=u.is_admin, is_disabled=u.is_disabled, created_at=u.created_at,
            vault_count=int(vc), item_count=int(ic), size_bytes=int(sb),
        )
        for u, vc, ic, sb in rows
    ]


@router.get("/users/{user_id}/vaults", response_model=List[VaultOut])
def user_vaults(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not db.query(User.id).filter(User.id == user_id).first():
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
    return db.query(Vault).filter(Vault.user_id == user_id).order_by(Vault.created_at.desc()).all()


@router.post("/users/{user_id}/toggle-disabled")
def toggle_disabled(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Không thể tự khóa tài khoản quản trị của mình")
    user.is_disabled = not user.is_disabled
    db.commit()
    return {"status": "success", "is_disabled": user.is_disabled}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Không thể tự xóa tài khoản quản trị của mình")

    vaults = db.query(Vault).filter(Vault.user_id == user_id).all()
    for vault in vaults:
        vault_dir = settings.VAULT_DIR / vault.folder_name
        if vault_dir.is_dir():
            shutil.rmtree(vault_dir, ignore_errors=True)
        if storage.enabled():
            storage.delete_keys([m.file_path for m in vault.media_items if m.file_url])
        db.delete(vault)

    db.query(AppSetting).filter(AppSetting.key == f"cookies_txt:{user_id}").delete()
    cookie_file = settings.COOKIES_DIR / f"user_{user_id}.txt"
    if cookie_file.exists():
        cookie_file.unlink()

    db.delete(user)
    db.commit()
    return {"status": "success", "message": f"Đã xóa tài khoản {user.email} và toàn bộ kho của họ"}
