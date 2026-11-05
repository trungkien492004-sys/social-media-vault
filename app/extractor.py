import os
import re
import time
import random
import unicodedata
import subprocess
import asyncio
import logging
import shutil
import sys
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
        original_url: Optional[str] = None,
        needs_ytdlp: bool = False,
        headers: Optional[Dict[str, str]] = None,
        cookies_path: Optional[Path] = None
    ):
        self.file_type = file_type  # "image" or "video"
        self.download_url = download_url
        self.file_extension = file_extension.lstrip(".").lower()
        self.caption = caption or ""
        self.thumbnail_url = thumbnail_url
        self.original_url = original_url or ""
        # True when the media is a split/HLS stream that only yt-dlp can fetch correctly
        self.needs_ytdlp = needs_ytdlp
        self.headers = headers or {}
        self.cookies_path = cookies_path

def normalize_url(url: str) -> str:
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    # Normalize Facebook URLs
    if "facebook.com" in url or "fb.com" in url or "fb.watch" in url:
        # If user copied friends suggestions link or profile_id param
        m = re.search(r'[?&]profile_id=(\d+)', url)
        if m:
            return f"https://www.facebook.com/profile.php?id={m.group(1)}"
        m_num = re.search(r'facebook\.com/(\d{10,25})(?:[/?]|$)', url)
        if m_num:
            return f"https://www.facebook.com/profile.php?id={m_num.group(1)}"

    return url

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
        data = {}
        for attempt in range(4):
            resp = await client.post(api_url, data={"url": url, "hd": 1}, headers=headers)
            data = resp.json() if resp.status_code == 200 else {}
            # TikWM free tier allows ~1 request/second: back off and retry
            if data.get("code") != 0 and "limit" in str(data.get("msg", "")).lower():
                await asyncio.sleep(1.3 + attempt)
                continue
            break
        if data:
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
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
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
                    await asyncio.sleep(1.1)

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

HAS_FFMPEG = shutil.which("ffmpeg") is not None
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "gif", "heic"}
VIDEO_EXTS = {"mp4", "mov", "m4v", "webm", "mkv"}

def _ytdlp_format() -> str:
    # With ffmpeg we can merge best video + best audio; without it only single-file formats play correctly.
    if HAS_FFMPEG:
        return "bv*+ba/b"
    return "b[ext=mp4]/b"

def _ytdlp_base_opts(cookies_file: Optional[Path]) -> Dict[str, Any]:
    opts: Dict[str, Any] = {
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'format': _ytdlp_format(),
        'http_headers': {'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9,vi;q=0.8'},
    }
    if HAS_FFMPEG:
        opts['merge_output_format'] = 'mp4'
    if cookies_file and cookies_file.exists() and cookies_file.stat().st_size > 0:
        opts['cookiefile'] = str(cookies_file)
    return opts

def extract_with_ytdlp(url: str, cookies_file: Optional[Path] = None, max_items: int = 25) -> List[ExtractedItem]:
    """
    Universal extraction using yt-dlp with cookies.txt support.
    Split (video+audio) or HLS streams are flagged needs_ytdlp so they are downloaded by yt-dlp itself.
    """
    items: List[ExtractedItem] = []
    ydl_opts = _ytdlp_base_opts(cookies_file)
    ydl_opts.update({'extract_flat': False, 'skip_download': True, 'playlist_items': f'1-{max_items}'})

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return items

            entries = [e for e in info['entries'] if e] if info.get('entries') else [info]

            for entry in entries:
                caption = entry.get('title') or entry.get('description') or ""
                thumbnail = entry.get('thumbnail')
                entry_url = entry.get('webpage_url') or url
                direct_url = entry.get('url')
                ext = (entry.get('ext') or 'mp4').lower()
                protocol = entry.get('protocol') or ''
                split = bool(entry.get('requested_formats')) and len(entry['requested_formats']) > 1
                needs_ytdlp = split or protocol.startswith('m3u8') or 'dash' in protocol or ext == 'm3u8'
                # TikTok CDN links reject plain HTTP clients (403); yt-dlp downloads them with the right session
                if 'tiktok.com' in entry_url:
                    needs_ytdlp = True

                if not direct_url and entry.get('requested_formats'):
                    direct_url = entry['requested_formats'][0].get('url')
                if not direct_url and entry.get('formats'):
                    valid = [f for f in entry['formats'] if f.get('url')]
                    if valid:
                        direct_url = valid[-1]['url']
                        ext = (valid[-1].get('ext') or ext).lower()
                if not direct_url:
                    continue

                file_type = "image" if ext in IMAGE_EXTS else "video"
                if file_type == "video" and (ext not in VIDEO_EXTS or needs_ytdlp):
                    ext = "mp4"

                items.append(ExtractedItem(
                    file_type=file_type,
                    download_url=entry_url if needs_ytdlp else direct_url,
                    file_extension=ext,
                    caption=caption[:300] if caption else "",
                    thumbnail_url=thumbnail,
                    original_url=entry_url,
                    needs_ytdlp=needs_ytdlp,
                    headers=entry.get('http_headers') or {},
                    cookies_path=cookies_file
                ))
    except Exception as e:
        logger.error(f"yt-dlp extraction error for {url}: {e}")

    return items

def extract_with_gallerydl(url: str, cookies_file: Optional[Path] = None, max_items: int = 25) -> List[ExtractedItem]:
    """
    Fallback for pages yt-dlp cannot handle (Facebook photos/albums/profiles, Instagram profiles,
    Threads posts...). gallery-dl prints direct CDN URLs with -g.
    """
    cmd = [sys.executable, "-m", "gallery_dl", "-g", "--range", f"1-{max_items}"]
    if cookies_file and cookies_file.exists() and cookies_file.stat().st_size > 0:
        cmd += ["--cookies", str(cookies_file)]
    cmd.append(url)

    items: List[ExtractedItem] = []
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    except Exception as e:
        logger.error(f"gallery-dl error for {url}: {e}")
        return items

    if proc.returncode != 0 and not proc.stdout.strip():
        logger.warning(f"gallery-dl returned {proc.returncode}: {proc.stderr[-300:]}")

    seen = set()
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("| "):  # URL delegated to youtube-dl; the yt-dlp pass handles those
            continue
        if not line.startswith("http") or line in seen:
            continue
        seen.add(line)
        path = line.split("?")[0].lower()
        last = path.rsplit("/", 1)[-1]
        ext = last.rsplit(".", 1)[-1] if "." in last else ""
        if ext in VIDEO_EXTS:
            ftype = "video"
        else:
            ftype, ext = "image", (ext if ext in IMAGE_EXTS else "jpg")
        items.append(ExtractedItem(
            file_type=ftype,
            download_url=line,
            file_extension=ext,
            caption="",
            thumbnail_url=line if ftype == "image" else None,
            original_url=url
        ))
        if len(items) >= max_items:
            break
    return items

def download_with_ytdlp_sync(item: ExtractedItem, target_stem: Path) -> Optional[Path]:
    """Download a split/HLS stream with yt-dlp (merging with ffmpeg when available)."""
    opts = _ytdlp_base_opts(item.cookies_path)
    opts.update({'outtmpl': str(target_stem) + '.%(ext)s', 'noplaylist': True, 'retries': 3})
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(item.download_url, download=True)
            if info and info.get('entries'):
                info = next((e for e in info['entries'] if e), None)
            if info:
                fp = (info.get('requested_downloads') or [{}])[0].get('filepath') or ydl.prepare_filename(info)
                if fp and Path(fp).exists():
                    return Path(fp)
    except Exception as e:
        logger.error(f"yt-dlp download error for {item.download_url}: {e}")
    for cand in target_stem.parent.glob(target_stem.name + ".*"):
        if cand.suffix not in (".part", ".ytdl"):
            return cand
    return None

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

    # 3b. gallery-dl fallback (Facebook photos/albums/profiles, Instagram/Threads profiles & posts)
    if not items and platform in ("facebook", "instagram", "threads", "other"):
        loop = asyncio.get_event_loop()
        items = await loop.run_in_executor(None, extract_with_gallerydl, url, cookies_path, max_items)

    # 4. Filter by user preference: "all", "image", "video"
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
    stem = f"{item_index:03d}_{item.file_type}_{int(time.time())}_{random.randint(100, 999)}"
    target_path = destination_folder / f"{stem}.{ext}"

    def build_result(path: Path) -> Dict[str, Any]:
        return {
            "file_type": item.file_type,
            "file_name": path.name,
            "file_path": f"{destination_folder.name}/{path.name}",
            "file_size": path.stat().st_size,
            "original_url": item.original_url,
            "caption": item.caption,
            "thumbnail_url": item.thumbnail_url
        }

    # Split / HLS streams: let yt-dlp download (and merge) them
    if item.needs_ytdlp:
        loop = asyncio.get_event_loop()
        out = await loop.run_in_executor(None, download_with_ytdlp_sync, item, destination_folder / stem)
        if out and out.exists() and out.stat().st_size > 0:
            return build_result(out)
        logger.warning(f"yt-dlp download failed for {item.download_url}")
        return None

    headers = {"User-Agent": UA, "Referer": item.original_url or "https://www.google.com/"}
    headers.update({k: v for k, v in item.headers.items() if k.lower() != "accept-encoding"})

    try:
        await asyncio.sleep(random.uniform(0.2, 0.5))

        async with client.stream("GET", item.download_url, headers=headers, follow_redirects=True, timeout=60.0) as resp:
            if resp.status_code == 200:
                with open(target_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=1024 * 64):
                        f.write(chunk)
                if target_path.stat().st_size > 0:
                    return build_result(target_path)
                target_path.unlink()
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
