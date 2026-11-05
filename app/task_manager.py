import os
import asyncio
import uuid
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, AsyncGenerator, Optional
import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app import storage
from app.database import SessionLocal
from app.models import Vault, MediaItem
from app.extractor import (
    detect_platform,
    sanitize_folder_name,
    extract_media_items,
    download_file
)

logger = logging.getLogger("task_manager")

class TaskManager:
    def __init__(self):
        # task_id -> asyncio.Queue of event dicts
        self.subscribers: Dict[str, list[asyncio.Queue]] = {}
        # task_id -> task status cache
        self.tasks: Dict[str, Dict[str, Any]] = {}
        # Limit how many extraction jobs run at once so batch downloads don't hammer the platforms
        self.semaphore = asyncio.Semaphore(3)

    def create_task(self) -> str:
        task_id = str(uuid.uuid4())
        self.tasks[task_id] = {
            "status": "pending",
            "progress": 0,
            "message": "Đang khởi tạo tiến trình...",
            "current": 0,
            "total": 0,
            "created_at": datetime.utcnow().isoformat()
        }
        self.subscribers[task_id] = []
        return task_id

    async def broadcast_event(self, task_id: str, data: Dict[str, Any]):
        data = {**data, "task_id": task_id}
        if task_id in self.tasks:
            self.tasks[task_id].update(data)
        
        # Broadcast to all listeners subscribed to this task
        if task_id in self.subscribers:
            for queue in self.subscribers[task_id]:
                await queue.put(data)

    async def event_generator(self, task_id: str) -> AsyncGenerator[str, None]:
        queue = asyncio.Queue()
        if task_id not in self.subscribers:
            self.subscribers[task_id] = []
        self.subscribers[task_id].append(queue)
        
        # Yield initial state if already existing
        initial_data = self.tasks.get(task_id, {"status": "pending", "message": "Đang kết nối..."})
        yield f"data: {json.dumps(initial_data, ensure_ascii=False)}\n\n"

        try:
            while True:
                data = await queue.get()
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                if data.get("status") in ["completed", "error"]:
                    break
        except asyncio.CancelledError:
            pass
        finally:
            if task_id in self.subscribers and queue in self.subscribers[task_id]:
                self.subscribers[task_id].remove(queue)

    async def multi_event_generator(self, task_ids: list) -> AsyncGenerator[str, None]:
        """One SSE connection that multiplexes events of several tasks (batch download)."""
        queue = asyncio.Queue()
        active = set()
        for tid in task_ids:
            if tid not in self.tasks:
                continue
            self.subscribers.setdefault(tid, []).append(queue)
            state = {**self.tasks[tid], "task_id": tid}
            yield f"data: {json.dumps(state, ensure_ascii=False)}\n\n"
            if state.get("status") not in ("completed", "error"):
                active.add(tid)

        try:
            while active:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                if data.get("status") in ("completed", "error"):
                    active.discard(data.get("task_id"))
            yield f"data: {json.dumps({'status': 'batch_done'})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            for tid in task_ids:
                if tid in self.subscribers and queue in self.subscribers[tid]:
                    self.subscribers[tid].remove(queue)

    async def run_extraction_task(self, task_id: str, *args, **kwargs):
        await self.broadcast_event(task_id, {
            "status": "queued",
            "message": "Đang chờ đến lượt xử lý..."
        })
        async with self.semaphore:
            await self._run_extraction_task(task_id, *args, **kwargs)

    async def _run_extraction_task(
        self,
        task_id: str,
        vault_id: int,
        url: str,
        custom_name: str,
        notes: Optional[str],
        media_type: str,
        max_items: int = 50
    ):
        db: Session = SessionLocal()
        vault = None
        try:
            vault = db.query(Vault).filter(Vault.id == vault_id).first()
            if not vault:
                await self.broadcast_event(task_id, {
                    "status": "error",
                    "message": f"Không tìm thấy kho lưu trữ (Vault ID {vault_id})"
                })
                return

            platform = detect_platform(url)
            clean_name = sanitize_folder_name(custom_name)
            folder_name = f"{clean_name}_{platform}_{vault_id}"
            vault_folder = settings.VAULT_DIR / folder_name
            vault_folder.mkdir(parents=True, exist_ok=True)

            vault.platform = platform
            vault.folder_name = folder_name
            vault.folder_path = str(vault_folder)
            vault.status = "downloading"
            db.commit()

            await self.broadcast_event(task_id, {
                "status": "analyzing",
                "progress": 5,
                "message": f"Đang quét dữ liệu từ {platform.upper()} (hỗ trợ cả video lẻ và toàn bộ kênh)...",
                "platform": platform,
                "vault_id": vault_id
            })

            # 1. Extraction step
            cookies_file = settings.COOKIES_FILE if settings.COOKIES_FILE.exists() else None
            extracted_items = await extract_media_items(
                url=url,
                platform=platform,
                media_filter=media_type,
                cookies_path=cookies_file,
                max_items=max_items
            )

            total_items = len(extracted_items)
            if total_items == 0:
                if platform == "facebook":
                    err_msg = "Facebook chặn xem trang này khi chưa đăng nhập (Facebook tự động chuyển sang trang Login). Hãy bấm nút 'Cài đặt Cookie' (góc trên bên phải) để nạp file cookies.txt của bạn một lần, sau đó hệ thống sẽ tải được ảnh/video từ trang này ngay!"
                elif platform == "instagram":
                    err_msg = "Instagram yêu cầu đăng nhập để xem trang cá nhân hoặc bài viết này. Hãy nạp file cookies.txt trong phần 'Cài đặt Cookie' (góc trên) để tiếp tục."
                else:
                    err_msg = "Không tìm thấy nội dung media nào từ liên kết này (có thể là bài viết riêng tư, hoặc liên kết không chứa file video/ảnh)."

                vault.status = "error"
                vault.error_message = err_msg
                db.commit()

                await self.broadcast_event(task_id, {
                    "status": "error",
                    "progress": 100,
                    "message": err_msg
                })
                return

            total_img_count = sum(1 for item in extracted_items if item.file_type == "image")
            total_vid_count = sum(1 for item in extracted_items if item.file_type == "video")

            await self.broadcast_event(task_id, {
                "status": "downloading",
                "progress": 10,
                "current": 0,
                "total": total_items,
                "message": f"Đã tìm thấy {total_items} mục ({total_img_count} ảnh, {total_vid_count} video). Bắt đầu tải về...",
                "total_images": total_img_count,
                "total_videos": total_vid_count
            })

            # 2. Download step
            saved_items_count = 0
            saved_images = 0
            saved_videos = 0
            total_bytes = 0

            async with httpx.AsyncClient(timeout=60.0) as client:
                for idx, item in enumerate(extracted_items, start=1):
                    result = await download_file(client, item, vault_folder, idx)
                    if result:
                        # Persist to Supabase Storage (if configured) and free local disk
                        file_url = None
                        if storage.enabled():
                            local_file = settings.VAULT_DIR / result["file_path"]
                            file_url = await storage.upload_file(client, local_file, result["file_path"])
                            if file_url:
                                try:
                                    local_file.unlink()
                                except Exception:
                                    pass
                        result["file_url"] = file_url

                        saved_items_count += 1
                        total_bytes += result["file_size"]
                        if result["file_type"] == "image":
                            saved_images += 1
                        else:
                            saved_videos += 1

                        # Save to database
                        media_db = MediaItem(
                            vault_id=vault.id,
                            file_type=result["file_type"],
                            file_name=result["file_name"],
                            file_path=result["file_path"],
                            file_size=result["file_size"],
                            original_url=result["original_url"],
                            caption=result["caption"],
                            thumbnail_url=result["thumbnail_url"],
                            file_url=result["file_url"]
                        )
                        db.add(media_db)
                        db.commit()
                        db.refresh(media_db)

                        progress = int(10 + (idx / total_items) * 85)
                        await self.broadcast_event(task_id, {
                            "status": "downloading",
                            "progress": progress,
                            "current": idx,
                            "total": total_items,
                            "message": f"Đã tải {idx}/{total_items}: {result['file_name']}",
                            "latest_item": {
                                "id": media_db.id,
                                "file_name": media_db.file_name,
                                "file_path": media_db.file_path,
                                "file_url": media_db.file_url,
                                "file_type": media_db.file_type,
                                "file_size": media_db.file_size
                            }
                        })
                    else:
                        logger.warning(f"Bỏ qua mục thứ {idx} do tải thất bại.")

            # 3. Finalize Vault in database
            vault.total_items = saved_items_count
            vault.total_images = saved_images
            vault.total_videos = saved_videos
            vault.total_size_bytes = total_bytes
            vault.status = "completed"
            db.commit()

            await self.broadcast_event(task_id, {
                "status": "completed",
                "progress": 100,
                "current": saved_items_count,
                "total": total_items,
                "message": f"Hoàn tất! Đã lưu thành công {saved_items_count} media ({saved_images} ảnh, {saved_videos} video).",
                "vault_id": vault.id
            })

        except Exception as e:
            logger.exception(f"Lỗi khi thực thi task {task_id}: {e}")
            if vault:
                vault.status = "error"
                vault.error_message = str(e)
                db.commit()
            await self.broadcast_event(task_id, {
                "status": "error",
                "progress": 100,
                "message": f"Đã xảy ra lỗi trong quá trình xử lý: {str(e)}"
            })
        finally:
            db.close()

task_manager = TaskManager()
