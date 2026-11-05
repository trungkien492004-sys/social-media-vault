"""
Optional persistent media storage on Supabase Storage (REST API, no SDK needed).

When SUPABASE_URL and SUPABASE_SERVICE_KEY are set, every downloaded file is uploaded to a
public bucket and its public URL is saved in the database. The local copy is then removed so
ephemeral hosts (Render Free) never run out of disk or lose data on restart.
"""
import logging
import mimetypes
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

import httpx

from app.config import settings

logger = logging.getLogger("storage")

# Supabase Storage Free plan rejects objects larger than 50 MB
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def enabled() -> bool:
    return bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY)


def _base() -> str:
    return settings.SUPABASE_URL.rstrip("/")


last_error: str = ""


def _headers(extra: Optional[dict] = None) -> dict:
    key = settings.SUPABASE_SERVICE_KEY.strip()
    h = {"apikey": key}
    # New-style keys (sb_secret_...) are not JWTs: they must only be sent in the apikey header.
    if not key.startswith("sb_"):
        h["Authorization"] = f"Bearer {key}"
    if extra:
        h.update(extra)
    return h


def _fail(msg: str) -> None:
    global last_error
    last_error = msg
    logger.warning("Supabase: %s", msg)


def public_url(key: str) -> str:
    return f"{_base()}/storage/v1/object/public/{settings.SUPABASE_BUCKET}/{quote(key)}"


async def ensure_bucket() -> None:
    """Create the public bucket if it does not exist yet."""
    if not enabled():
        return
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{_base()}/storage/v1/bucket",
                headers=_headers({"Content-Type": "application/json"}),
                json={"id": settings.SUPABASE_BUCKET, "name": settings.SUPABASE_BUCKET, "public": True},
            )
            if resp.status_code in (200, 201):
                logger.info("Created Supabase bucket '%s'", settings.SUPABASE_BUCKET)
            elif resp.status_code not in (400, 409):  # already exists
                _fail(f"bucket {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        _fail(f"bucket error: {e}")


async def upload_file(client: httpx.AsyncClient, local_path: Path, key: str) -> Optional[str]:
    """Upload a local file; returns its public URL or None when it could not be stored."""
    if not enabled():
        return None
    size = local_path.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        logger.warning("%s is %.1f MB, above the 50 MB Supabase limit; keeping it on local disk", local_path.name, size / 1048576)
        return None

    content_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
    try:
        resp = await client.post(
            f"{_base()}/storage/v1/object/{settings.SUPABASE_BUCKET}/{quote(key)}",
            headers=_headers({"Content-Type": content_type, "x-upsert": "true"}),
            content=local_path.read_bytes(),
            timeout=120.0,
        )
        if resp.status_code in (200, 201):
            return public_url(key)
        _fail(f"upload {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        _fail(f"upload error: {e}")
    return None


def delete_keys(keys: List[str]) -> None:
    """Remove objects from the bucket (best effort)."""
    if not enabled() or not keys:
        return
    try:
        resp = httpx.request(
            "DELETE",
            f"{_base()}/storage/v1/object/{settings.SUPABASE_BUCKET}",
            headers=_headers({"Content-Type": "application/json"}),
            json={"prefixes": keys},
            timeout=30.0,
        )
        if resp.status_code not in (200, 204):
            logger.warning("Supabase delete failed (%s): %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("Supabase delete error: %s", e)
