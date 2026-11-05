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


@router.get("/diagnose")
def diagnose(
    url: str = "https://www.facebook.com/watch/?v=10153231379946729",
    admin: User = Depends(require_admin),
):
    """
    Shows what THIS SERVER sees when it opens a link (is Facebook/Instagram blocking the host?).
    Never returns cookie contents.
    """
    import time as _time
    import httpx
    import yt_dlp
    from app.extractor import UA, extract_with_gallerydl

    report = {"url": url, "server_ip": None, "http": None, "ytdlp": None, "gallerydl": None, "has_cookies": False}

    try:
        report["server_ip"] = httpx.get("https://api.ipify.org", timeout=10).text
    except Exception as e:
        report["server_ip"] = f"không lấy được: {e}"

    cookie_file = settings.COOKIES_DIR / f"user_{admin.id}.txt"
    report["has_cookies"] = cookie_file.exists() and cookie_file.stat().st_size > 0

    t0 = _time.time()
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=20, follow_redirects=True)
        body = r.text.lower()
        report["http"] = {
            "status": r.status_code,
            "final_url": str(r.url)[:200],
            "redirected_to_login": "/login" in str(r.url).lower() or "log in to facebook" in body or "log into facebook" in body,
            "has_video_data": any(k in body for k in ("playable_url", "browser_native", "video_url", "og:video")),
            "seconds": round(_time.time() - t0, 1),
        }
    except Exception as e:
        report["http"] = {"error": str(e)[:300]}

    t0 = _time.time()
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
    if report["has_cookies"]:
        opts["cookiefile"] = str(cookie_file)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            report["ytdlp"] = {"ok": bool(info), "title": (info or {}).get("title"), "seconds": round(_time.time() - t0, 1)}
    except Exception as e:
        report["ytdlp"] = {"ok": False, "error": str(e)[:400], "seconds": round(_time.time() - t0, 1)}

    t0 = _time.time()
    try:
        found = extract_with_gallerydl(url, cookie_file if report["has_cookies"] else None, 5)
        report["gallerydl"] = {"ok": bool(found), "items": len(found), "seconds": round(_time.time() - t0, 1)}
    except Exception as e:
        report["gallerydl"] = {"ok": False, "error": str(e)[:300]}

    return report
