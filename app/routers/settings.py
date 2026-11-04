import os
from datetime import datetime
from typing import List
from fastapi import APIRouter, UploadFile, File, HTTPException
from app.config import settings
from app.schemas import CookieStatus

router = APIRouter(prefix="/api/settings", tags=["Settings"])

@router.get("/cookies", response_model=CookieStatus)
def get_cookie_status():
    cookie_path = settings.COOKIES_FILE
    if not cookie_path.exists():
        return CookieStatus(
            exists=False,
            size_bytes=0,
            platforms_detected=[],
            last_modified=None
        )

    try:
        size = cookie_path.stat().st_size
        mtime = datetime.fromtimestamp(cookie_path.stat().st_mtime).strftime("%d/%m/%Y %H:%M:%S")

        # Detect platforms inside cookies.txt
        platforms = []
        with open(cookie_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read().lower()
            if "facebook.com" in content:
                platforms.append("Facebook")
            if "instagram.com" in content:
                platforms.append("Instagram")
            if "threads.net" in content:
                platforms.append("Threads")
            if "tiktok.com" in content:
                platforms.append("TikTok")

        return CookieStatus(
            exists=True,
            size_bytes=size,
            platforms_detected=platforms,
            last_modified=mtime
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi đọc file cookies: {str(e)}")

@router.post("/cookies")
async def upload_cookies(file: UploadFile = File(...)):
    if not file.filename.endswith(".txt"):
        raise HTTPException(status_code=400, detail="Vui lòng chỉ tải lên tệp định dạng .txt (cookies.txt)")

    try:
        content = await file.read()
        settings.COOKIES_DIR.mkdir(parents=True, exist_ok=True)
        with open(settings.COOKIES_FILE, "wb") as f:
            f.write(content)

        return {"status": "success", "message": "Đã lưu cookies.txt thành công! Hệ thống sẵn sàng cào nội dung cần đăng nhập."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi lưu file cookies: {str(e)}")

@router.delete("/cookies")
def delete_cookies():
    cookie_path = settings.COOKIES_FILE
    if cookie_path.exists():
        try:
            cookie_path.unlink()
            return {"status": "success", "message": "Đã xóa file cookies thành công"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Không thể xóa file cookies: {str(e)}")
    return {"status": "success", "message": "File cookies không tồn tại"}
