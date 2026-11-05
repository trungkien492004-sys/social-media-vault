import asyncio
import random
import tempfile
import time
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import storage
from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.media_tools import build_video_filter, get_ffmpeg, run_ffmpeg_edit, sniff_image_ext
from app.models import MediaItem, User, Vault
from app.routers.vaults import get_owned_vault

router = APIRouter(prefix="/api/vaults/{vault_id}/media", tags=["Media"])

MAX_IMAGE_BYTES = 30 * 1024 * 1024
_video_gate = asyncio.Semaphore(1)  # ffmpeg is CPU heavy; one edit at a time keeps the host responsive


class DeleteMediaRequest(BaseModel):
    ids: List[int] = Field(..., min_length=1, max_length=500)


class VideoEditRequest(BaseModel):
    start: float = Field(0, ge=0)
    end: Optional[float] = Field(None, ge=0)
    rotate: int = Field(0)
    flip_h: bool = False
    flip_v: bool = False
    brightness: float = Field(1.0, ge=0.2, le=2.0)
    contrast: float = Field(1.0, ge=0.2, le=2.0)
    saturation: float = Field(1.0, ge=0.0, le=3.0)
    mode: str = Field("replace", pattern="^(replace|copy)$")


def recount(vault: Vault, db: Session) -> None:
    items = db.query(MediaItem).filter(MediaItem.vault_id == vault.id).all()
    vault.total_items = len(items)
    vault.total_images = sum(1 for i in items if i.file_type == "image")
    vault.total_videos = sum(1 for i in items if i.file_type == "video")
    vault.total_size_bytes = sum(i.file_size or 0 for i in items)


def remove_item_files(item: MediaItem) -> None:
    local = settings.VAULT_DIR / item.file_path
    if local.exists():
        try:
            local.unlink()
        except Exception:
            pass
    if item.file_url:
        storage.delete_keys([item.file_path])


def get_item(db: Session, vault: Vault, media_id: int) -> MediaItem:
    item = db.query(MediaItem).filter(MediaItem.id == media_id, MediaItem.vault_id == vault.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Không tìm thấy tệp trong kho")
    return item


def check_quota_for(db: Session, user: User, vault: Vault, extra_bytes: int) -> None:
    if user.is_admin or settings.USER_QUOTA_MB <= 0:
        return
    from sqlalchemy import func
    used = db.query(func.coalesce(func.sum(Vault.total_size_bytes), 0)).filter(Vault.user_id == vault.user_id).scalar() or 0
    if used + extra_bytes > settings.USER_QUOTA_MB * 1024 * 1024:
        raise HTTPException(status_code=403, detail=f"Vượt giới hạn dung lượng {settings.USER_QUOTA_MB} MB. Hãy xóa bớt tệp hoặc chọn 'Ghi đè'.")


async def store_new_file(vault: Vault, local_path: Path) -> Optional[str]:
    """Upload to persistent storage when configured and free the local copy. Returns the public URL or None."""
    if not storage.enabled():
        return None
    key = f"{vault.folder_name}/{local_path.name}"
    async with httpx.AsyncClient(timeout=120.0) as client:
        url = await storage.upload_file(client, local_path, key)
    if url:
        try:
            local_path.unlink()
        except Exception:
            pass
    return url


def new_name(prefix: str, ext: str) -> str:
    return f"edited_{prefix}_{int(time.time())}_{random.randint(100, 999)}.{ext}"


async def apply_result(db: Session, vault: Vault, item: MediaItem, new_local: Path, mode: str) -> MediaItem:
    """Save an edited file either over the original item or as a new copy."""
    size = new_local.stat().st_size
    file_name = new_local.name
    file_path = f"{vault.folder_name}/{file_name}"
    file_url = await store_new_file(vault, new_local)

    if mode == "replace":
        old = MediaItem(file_path=item.file_path, file_url=item.file_url)  # detached snapshot for cleanup
        remove_item_files(old)
        item.file_name = file_name
        item.file_path = file_path
        item.file_size = size
        item.file_url = file_url
        target = item
    else:
        target = MediaItem(
            vault_id=vault.id, file_type=item.file_type, file_name=file_name, file_path=file_path,
            file_size=size, original_url=item.original_url, caption=item.caption,
            thumbnail_url=item.thumbnail_url, file_url=file_url,
        )
        db.add(target)
    db.flush()
    recount(vault, db)
    db.commit()
    db.refresh(target)
    return target


def media_json(m: MediaItem) -> dict:
    return {
        "id": m.id, "vault_id": m.vault_id, "file_type": m.file_type, "file_name": m.file_name,
        "file_path": m.file_path, "file_size": m.file_size, "file_url": m.file_url, "caption": m.caption,
    }


@router.post("/delete")
def delete_media(vault_id: int, req: DeleteMediaRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    vault = get_owned_vault(db, vault_id, user)
    items = db.query(MediaItem).filter(MediaItem.vault_id == vault.id, MediaItem.id.in_(req.ids)).all()
    if not items:
        raise HTTPException(status_code=404, detail="Không tìm thấy tệp cần xóa")
    remote_keys = []
    for item in items:
        local = settings.VAULT_DIR / item.file_path
        if local.exists():
            try:
                local.unlink()
            except Exception:
                pass
        if item.file_url:
            remote_keys.append(item.file_path)
        db.delete(item)
    db.flush()
    recount(vault, db)
    db.commit()
    if remote_keys:
        storage.delete_keys(remote_keys)
    return {"status": "success", "deleted": len(items), "remaining": vault.total_items}


@router.get("/{media_id}/raw")
async def raw_media(vault_id: int, media_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Same-origin copy of a file so the browser editor can draw it on a canvas without CORS problems."""
    vault = get_owned_vault(db, vault_id, user)
    item = get_item(db, vault, media_id)
    local = settings.VAULT_DIR / item.file_path
    if local.exists():
        return FileResponse(local)
    if item.file_url:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(item.file_url)
        if resp.status_code == 200:
            return Response(content=resp.content, media_type=resp.headers.get("content-type", "application/octet-stream"))
    raise HTTPException(status_code=404, detail="Tệp không còn tồn tại")


@router.post("/{media_id}/edit-image")
async def edit_image(
    vault_id: int,
    media_id: int,
    file: UploadFile = File(...),
    mode: str = Form("replace"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if mode not in ("replace", "copy"):
        raise HTTPException(status_code=422, detail="Chế độ lưu không hợp lệ")
    vault = get_owned_vault(db, vault_id, user)
    if vault.user_id != user.id:
        raise HTTPException(status_code=403, detail="Chỉ chủ kho mới được chỉnh sửa")
    item = get_item(db, vault, media_id)
    if item.file_type != "image":
        raise HTTPException(status_code=400, detail="Tệp này không phải ảnh")

    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Ảnh sau chỉnh sửa quá lớn")
    ext = sniff_image_ext(data)
    if not ext:
        raise HTTPException(status_code=400, detail="Định dạng ảnh không hợp lệ")
    if mode == "copy":
        check_quota_for(db, user, vault, len(data))

    folder = settings.VAULT_DIR / vault.folder_name
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / new_name(str(item.id), ext)
    out.write_bytes(data)
    target = await apply_result(db, vault, item, out, mode)
    return media_json(target)


@router.post("/{media_id}/edit-video")
async def edit_video(
    vault_id: int,
    media_id: int,
    req: VideoEditRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    vault = get_owned_vault(db, vault_id, user)
    if vault.user_id != user.id:
        raise HTTPException(status_code=403, detail="Chỉ chủ kho mới được chỉnh sửa")
    item = get_item(db, vault, media_id)
    if item.file_type != "video":
        raise HTTPException(status_code=400, detail="Tệp này không phải video")
    if req.rotate not in (0, 90, 180, 270):
        raise HTTPException(status_code=422, detail="Góc xoay không hợp lệ")
    if req.end is not None and req.end <= req.start:
        raise HTTPException(status_code=422, detail="Điểm cuối phải lớn hơn điểm đầu")
    if not get_ffmpeg():
        raise HTTPException(status_code=501, detail="Máy chủ chưa có ffmpeg nên chưa chỉnh sửa được video")
    if req.mode == "copy":
        check_quota_for(db, user, vault, item.file_size or 0)

    folder = settings.VAULT_DIR / vault.folder_name
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / new_name(str(item.id), "mp4")
    duration = (req.end - req.start) if req.end is not None else None
    vfilter = build_video_filter(req.rotate, req.flip_h, req.flip_v, req.brightness, req.contrast, req.saturation)

    tmp_src: Optional[Path] = None
    try:
        src = settings.VAULT_DIR / item.file_path
        if not src.exists():
            if not item.file_url:
                raise HTTPException(status_code=404, detail="Tệp video gốc không còn tồn tại")
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
            tmp.close()
            tmp_src = Path(tmp.name)
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                async with client.stream("GET", item.file_url) as resp:
                    if resp.status_code != 200:
                        raise HTTPException(status_code=502, detail="Không tải được video gốc để chỉnh sửa")
                    with open(tmp_src, "wb") as f:
                        async for chunk in resp.aiter_bytes(1024 * 256):
                            f.write(chunk)
            src = tmp_src

        loop = asyncio.get_event_loop()
        async with _video_gate:
            error = await loop.run_in_executor(None, run_ffmpeg_edit, src, out, req.start, duration, vfilter)
        if error:
            if out.exists():
                out.unlink()
            raise HTTPException(status_code=500, detail=error)
    finally:
        if tmp_src and tmp_src.exists():
            try:
                tmp_src.unlink()
            except Exception:
                pass

    target = await apply_result(db, vault, item, out, req.mode)
    return media_json(target)
