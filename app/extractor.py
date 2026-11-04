import os
import re
import time
import random
import unicodedata
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
import httpx
import yt_dlp
from app.config import settings

logger = logging.getLogger("extractor")
logging.basicConfig(level=logging.INFO)

class ExtractedItem:
    def __init__(
        self,
        file_type: str,
        download_url: str,
        file_extension: str,
        caption: Optional[str] = None,
        thumbnail_url: Optional[str] = None,
        original_url: Optional[str] = None
    ):
        self.file_type = file_type  # "image" or "video"
        self.download_url = download_url
        self.file_extension = file_extension.lstrip(".").lower()
        self.caption = caption or ""
        self.thumbnail_url = thumbnail_url
        self.original_url = original_url or ""

def detect_platform(url: str) -> str:
    url_lower = url.lower()
    if "tiktok.com" in url_lower:
        return "tiktok"
    elif "instagram.com" in url_lower:
        return "instagram"
    elif "threads.net" in url_lower:
        return "threads"
    elif "facebook.com" in url_lower or "fb.watch" in url_lower or "fb.com" in url_lower:
        return "facebook"
    return "other"

def sanitize_folder_name(name: str) -> str:
    # Convert Vietnamese diacritics to clean standard ASCII (e.g., 'Thầy Kiên' -> 'Thay_Kien')
    normalized = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('utf-8')
    clean = re.sub(r'[^a-zA-Z0-9_\- ]', '', normalized).strip().replace(' ', '_')
    return clean[:50] or "Vault"

async def extract_tiktok_tikwm(url: str) -> List[ExtractedItem]:
    """
    Extract TikTok video HD without watermark or image album using TikWM API
    """
    items: List[ExtractedItem] = []
    api_url = "https://www.tikwm.com/api/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    
    async with httpx.AsyncClient(timeout=25.0) as client:
        try:
            resp = await client.post(api_url, data={"url": url, "hd": 1}, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0 and "data" in data:
                    item_data = data["data"]
                    caption = item_data.get("title", "")
                    
                    # Case 1: Photo Slideshow
                    images = item_data.get("images", [])
                    if images and isinstance(images, list):
                        for idx, img_url in enumerate(images):
                            items.append(ExtractedItem(
                                file_type="image",
                                download_url=img_url,
                                file_extension="jpg",
                                caption=caption,
                                thumbnail_url=img_url,
                                original_url=url
                            ))
                        return items
                    
                    # Case 2: HD Video without Watermark
                    video_url = item_data.get("hdplay") or item_data.get("play")
                    if video_url:
                        # Ensure absolute URL
                        if video_url.startswith("/"):
                            video_url = f"https://www.tikwm.com{video_url}"
                        cover = item_data.get("cover") or item_data.get("origin_cover")
                        items.append(ExtractedItem(
                            file_type="video",
                            download_url=video_url,
                            file_extension="mp4",
                            caption=caption,
                            thumbnail_url=cover,
                            original_url=url
                        ))
                        return items
        except Exception as e:
            logger.warning(f"TikWM extraction failed for {url}: {e}, falling back to yt-dlp")
    return items

def extract_with_ytdlp(url: str, cookies_file: Optional[Path] = None, max_items: int = 50) -> List[ExtractedItem]:
    """
    Universal extraction using yt-dlp with optional cookies.txt support
    """
    items: List[ExtractedItem] = []
    
    ydl_opts: Dict[str, Any] = {
        'extract_flat': False,
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'playlist_items': f'1-{max_items}',
        'format': 'bestvideo+bestaudio/best',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9,vi;q=0.8',
        }
    }
    
    if cookies_file and cookies_file.exists() and cookies_file.stat().st_size > 0:
        ydl_opts['cookiefile'] = str(cookies_file)
        logger.info(f"Using cookies file: {cookies_file}")
        
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return items
            
            entries = []
            if 'entries' in info and info['entries']:
                entries = [e for e in info['entries'] if e]
            else:
                entries = [info]
                
            for entry in entries:
                caption = entry.get('title') or entry.get('description') or ""
                thumbnail = entry.get('thumbnail')
                entry_url = entry.get('webpage_url') or url
                
                # Check if it has formats or direct url
                direct_url = entry.get('url')
                ext = entry.get('ext') or 'mp4'
                
                # Handle images vs videos
                # In yt-dlp, some Instagram posts are images (ext is jpg/webp/png)
                if ext in ['jpg', 'jpeg', 'png', 'webp']:
                    file_type = "image"
                else:
                    file_type = "video"
                    
                # If direct_url not set, check requested_downloads or formats
                if not direct_url and 'formats' in entry and entry['formats']:
                    # Pick best format with both audio and video or highest resolution
                    formats = entry['formats']
                    # filter formats with url
                    valid_formats = [f for f in formats if f.get('url')]
                    if valid_formats:
                        best = valid_formats[-1]
                        direct_url = best.get('url')
                        if best.get('ext'):
                            ext = best.get('ext')
                
                if direct_url:
                    items.append(ExtractedItem(
                        file_type=file_type,
                        download_url=direct_url,
                        file_extension=ext,
                        caption=caption[:300] if caption else "",
                        thumbnail_url=thumbnail,
                        original_url=entry_url
                    ))
    except Exception as e:
        logger.error(f"yt-dlp extraction error for {url}: {e}")
        
    return items

async def extract_media_items(
    url: str,
    platform: str,
    media_filter: str = "all",
    cookies_path: Optional[Path] = None
) -> List[ExtractedItem]:
    """
    Main extraction dispatcher
    """
    items: List[ExtractedItem] = []
    
    # 1. Specialized TikTok Extraction
    if platform == "tiktok":
        tiktok_items = await extract_tiktok_tikwm(url)
        if tiktok_items:
            items = tiktok_items
    
    # 2. If no items yet, fallback or default to yt-dlp
    if not items:
        # Run yt-dlp in thread pool since yt-dlp is synchronous
        import asyncio
        loop = asyncio.get_event_loop()
        items = await loop.run_in_executor(
            None,
            extract_with_ytdlp,
            url,
            cookies_path,
            settings.MAX_ITEMS_PER_TASK
        )
        
    # 3. Filter by user preference: "all", "image", "video"
    if media_filter == "image":
        items = [item for item in items if item.file_type == "image"]
    elif media_filter == "video":
        items = [item for item in items if item.file_type == "video"]
        
    return items

async def download_file(
    client: httpx.AsyncClient,
    item: ExtractedItem,
    destination_folder: Path,
    item_index: int
) -> Optional[Dict[str, Any]]:
    """
    Download a single media item with rate-limit safety & proper headers
    """
    # Generate clean, standard filename
    ext = item.file_extension if item.file_extension else ("mp4" if item.file_type == "video" else "jpg")
    file_name = f"{item_index:03d}_{item.file_type}_{int(time.time())}_{random.randint(100, 999)}.{ext}"
    target_path = destination_folder / file_name

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Referer": item.original_url or "https://www.google.com/"
    }

    try:
        # Rate-limiting: random delay between 0.5s - 1.8s
        delay = random.uniform(settings.RATE_LIMIT_DELAY_MIN, settings.RATE_LIMIT_DELAY_MAX)
        await time_sleep_async(delay)

        async with client.stream("GET", item.download_url, headers=headers, follow_redirects=True, timeout=60.0) as resp:
            if resp.status_code == 200:
                total_bytes = 0
                with open(target_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=1024 * 64):
                        f.write(chunk)
                        total_bytes += len(chunk)

                return {
                    "file_type": item.file_type,
                    "file_name": file_name,
                    "file_path": f"{destination_folder.name}/{file_name}",
                    "file_size": total_bytes,
                    "original_url": item.original_url,
                    "caption": item.caption,
                    "thumbnail_url": item.thumbnail_url
                }
            else:
                logger.warning(f"Download failed with status {resp.status_code} for {item.download_url}")
    except Exception as e:
        logger.error(f"Error downloading {item.download_url}: {e}")
        if target_path.exists():
            try:
                target_path.unlink()
            except Exception:
                pass
    return None

async def time_sleep_async(seconds: float):
    import asyncio
    await asyncio.sleep(seconds)
