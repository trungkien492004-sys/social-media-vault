import os
import re
import time
import random
import unicodedata
import subprocess
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
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
    elif "zalo.me" in url_lower or "zadn.vn" in url_lower:
        return "zalo"
    return "other"

def sanitize_folder_name(name: str) -> str:
    # Convert Vietnamese diacritics to clean standard ASCII (e.g., 'Thầy Kiên' -> 'Thay_Kien')
    normalized = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('utf-8')
    clean = re.sub(r'[^a-zA-Z0-9_\- ]', '', normalized).strip().replace(' ', '_')
    return clean[:50] or "Vault"

async def extract_single_tiktok_tikwm(client: httpx.AsyncClient, url: str) -> List[ExtractedItem]:
    """
    Extract single TikTok video HD without watermark or image album using TikWM API
    """
    items: List[ExtractedItem] = []
    api_url = "https://www.tikwm.com/api/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }

    try:
        resp = await client.post(api_url, data={"url": url, "hd": 1}, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 0 and "data" in data:
                item_data = data["data"]
                caption = item_data.get("title", "")

                # Case 1: Photo Slideshow
                images = item_data.get("images", [])
                if images and isinstance(images, list) and len(images) > 0:
                    for img_url in images:
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
        logger.warning(f"TikWM extraction failed for {url}: {e}")
    return items

def get_tiktok_profile_posts_sync(profile_url: str, max_count: int = 15) -> List[str]:
    """
    Use gallery-dl via python -m to solve TikTok JS challenge and extract user post URLs
    """
    import sys
    clean = profile_url.rstrip("/")
    if not clean.endswith("/posts"):
        clean += "/posts"

    cmd = [sys.executable, "-m", "gallery_dl", "-s", "--range", f"1-{max_count}", clean]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        output = proc.stdout + "\n" + proc.stderr
        urls = list(dict.fromkeys(re.findall(r'https?://(?:www\.)?tiktok\.com/@[^/]+/video/\d+', output)))
        return urls[:max_count]
    except Exception as e:
        logger.error(f"gallery-dl profile extraction error: {e}")
        return []

async def extract_zalo_media(url: str) -> List[ExtractedItem]:
    """
    Extract video/images from Zalo Video (zalo.me/video), Zalo OA or direct ZADN CDN media
    """
    items: List[ExtractedItem] = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7"
    }

    # Case 1: Direct media URL (e.g. *.zadn.vn or *.mp4 / *.jpg)
    url_clean = url.split("?")[0].lower()
    if any(url_clean.endswith(ext) for ext in [".mp4", ".mov", ".m4v"]):
        items.append(ExtractedItem(
            file_type="video",
            download_url=url,
            file_extension="mp4",
            caption="Video từ Zalo",
            original_url=url
        ))
        return items
    elif any(url_clean.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
        items.append(ExtractedItem(
            file_type="image",
            download_url=url,
            file_extension="jpg",
            caption="Ảnh từ Zalo",
            original_url=url
        ))
        return items

    # Case 2: Scrape Zalo Web Page / Zalo Video
    try:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                html = resp.text

                # Extract OpenGraph title / caption
                title_match = re.search(r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']', html)
                caption = title_match.group(1) if title_match else "Nội dung Zalo"

                # Check og:video
                video_match = re.search(r'<meta[^>]*property=["\']og:video(?::url)?["\'][^>]*content=["\']([^"\']+)["\']', html)
                if not video_match:
                    video_match = re.search(r'<video[^>]*src=["\']([^"\']+)["\']', html)
                if not video_match:
                    video_match = re.search(r'<source[^>]*src=["\']([^"\']+\.mp4[^"\']*)["\']', html)

                if video_match:
                    v_url = video_match.group(1).replace("&amp;", "&")
                    if v_url.startswith("//"):
                        v_url = "https:" + v_url
                    items.append(ExtractedItem(
                        file_type="video",
                        download_url=v_url,
                        file_extension="mp4",
                        caption=caption,
                        original_url=url
                    ))
                    return items

                # Check og:image or all images
                img_match = re.search(r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', html)
                if img_match:
                    img_url = img_match.group(1).replace("&amp;", "&")
                    if img_url.startswith("//"):
                        img_url = "https:" + img_url
                    items.append(ExtractedItem(
                        file_type="image",
                        download_url=img_url,
                        file_extension="jpg",
                        caption=caption,
                        original_url=url
                    ))
                    return items

                # Extract zadn.vn media URLs
                zadn_urls = list(dict.fromkeys(re.findall(r'https?://[^\s"\'<>]+\.zadn\.vn/[^\s"\'<>]+', html)))
                for z_url in zadn_urls[:10]:
                    z_clean = z_url.split("?")[0].lower()
                    f_type = "video" if any(z_clean.endswith(e) for e in [".mp4", ".mov"]) else "image"
                    items.append(ExtractedItem(
                        file_type=f_type,
                        download_url=z_url,
                        file_extension="mp4" if f_type == "video" else "jpg",
                        caption=caption,
                        original_url=url
                    ))

    except Exception as e:
        logger.error(f"Zalo extraction error: {e}")

    return items

async def extract_tiktok_media(url: str, cookies_path: Optional[Path] = None, max_items: int = 50) -> List[ExtractedItem]:
    """
    Handles both TikTok profile/account links and single post/video links
    """
    items: List[ExtractedItem] = []
    is_single_video = ("/video/" in url) or ("vt.tiktok.com" in url) or ("vm.tiktok.com" in url)

    async with httpx.AsyncClient(timeout=20.0) as client:
        if is_single_video:
            # Single video/slide
            items = await extract_single_tiktok_tikwm(client, url)
            if items:
                return items
        else:
            # Profile link: Extract posts up to requested max_items
            target_limit = min(max_items, 100)
            loop = asyncio.get_event_loop()
            post_urls = await loop.run_in_executor(None, get_tiktok_profile_posts_sync, url, target_limit)

            if post_urls:
                logger.info(f"Processing {len(post_urls)} posts from TikTok profile...")
                for p_url in post_urls:
                    post_items = await extract_single_tiktok_tikwm(client, p_url)
                    if post_items:
                        items.extend(post_items)
                    await asyncio.sleep(0.4)

                if items:
                    return items

    # Fallback to yt-dlp
    loop = asyncio.get_event_loop()
    fallback_items = await loop.run_in_executor(
        None,
        extract_with_ytdlp,
        url,
        cookies_path,
        max_items
    )
    if fallback_items:
        items.extend(fallback_items)

    return items

def extract_with_ytdlp(url: str, cookies_file: Optional[Path] = None, max_items: int = 25) -> List[ExtractedItem]:
    """
    Universal extraction using yt-dlp with cookies.txt support
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
                direct_url = entry.get('url')
                ext = entry.get('ext') or 'mp4'

                if ext in ['jpg', 'jpeg', 'png', 'webp']:
                    file_type = "image"
                else:
                    file_type = "video"

                if not direct_url and 'formats' in entry and entry['formats']:
                    valid_formats = [f for f in entry['formats'] if f.get('url')]
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
    cookies_path: Optional[Path] = None,
    max_items: int = 50
) -> List[ExtractedItem]:
    """
    Main extraction dispatcher
    """
    items: List[ExtractedItem] = []

    # 1. Specialized TikTok Extraction (Profile or Video)
    if platform == "tiktok":
        items = await extract_tiktok_media(url, cookies_path, max_items)

    # 2. Specialized Zalo Extraction (Zalo Video, OA, Direct Media)
    elif platform == "zalo":
        items = await extract_zalo_media(url)

    # 3. Other platforms (Instagram, Threads, Facebook) or fallback
    if not items:
        loop = asyncio.get_event_loop()
        items = await loop.run_in_executor(
            None,
            extract_with_ytdlp,
            url,
            cookies_path,
            max_items
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
    ext = item.file_extension if item.file_extension else ("mp4" if item.file_type == "video" else "jpg")
    file_name = f"{item_index:03d}_{item.file_type}_{int(time.time())}_{random.randint(100, 999)}.{ext}"
    target_path = destination_folder / file_name

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Referer": item.original_url or "https://www.google.com/"
    }

    try:
        # Shorter, smoother delay (0.3s - 0.8s) for faster completion
        await asyncio.sleep(random.uniform(0.3, 0.8))

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
