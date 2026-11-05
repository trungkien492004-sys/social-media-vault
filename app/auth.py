"""
Minimal account system: email + password, signed session cookie.
No extra dependencies (hashlib.scrypt + HMAC).
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.models import AppSetting, User

COOKIE_NAME = "vault_session"
TOKEN_TTL_SECONDS = 30 * 24 * 3600

_secret_cache: Optional[bytes] = None


def _get_secret() -> bytes:
    """SECRET_KEY from the environment, otherwise a random key stored once in the database."""
    global _secret_cache
    if _secret_cache:
        return _secret_cache
    env = os.getenv("SECRET_KEY", "").strip()
    if env:
        _secret_cache = env.encode()
        return _secret_cache
    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.key == "secret_key").first()
        if not row:
            row = AppSetting(key="secret_key", value=secrets.token_hex(32))
            db.add(row)
            db.commit()
            db.refresh(row)
        _secret_cache = row.value.encode()
        return _secret_cache
    finally:
        db.close()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, hash_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(digest.hex(), hash_hex)
    except Exception:
        return False


def create_token(user_id: int) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"uid": user_id, "exp": int(time.time()) + TOKEN_TTL_SECONDS}).encode()
    ).decode()
    sig = hmac.new(_get_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def read_token(token: str) -> Optional[int]:
    try:
        payload, sig = token.rsplit(".", 1)
        expected = hmac.new(_get_secret(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload.encode()))
        if data["exp"] < time.time():
            return None
        return int(data["uid"])
    except Exception:
        return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    uid = read_token(token) if token else None
    user = db.query(User).filter(User.id == uid).first() if uid else None
    if not user or user.is_disabled:
        raise HTTPException(status_code=401, detail="Vui lòng đăng nhập")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Chỉ quản trị viên mới được dùng chức năng này")
    return user


def cookie_secure(request: Request) -> bool:
    return request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
