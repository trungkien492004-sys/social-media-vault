import os
import re
import time
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.auth import (
    COOKIE_NAME, TOKEN_TTL_SECONDS, cookie_secure, create_token, get_current_user,
    hash_password, verify_password,
)
from app.database import get_db
from app.models import User, Vault
from app.schemas import AuthRequest, UserOut

router = APIRouter(prefix="/api/auth", tags=["Auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Very small in-memory brute-force guard: key -> list of failure timestamps
_failures: Dict[str, List[float]] = {}
MAX_FAILURES = 6
WINDOW_SECONDS = 15 * 60


def _blocked(key: str) -> bool:
    now = time.time()
    recent = [t for t in _failures.get(key, []) if now - t < WINDOW_SECONDS]
    _failures[key] = recent
    return len(recent) >= MAX_FAILURES


def _set_session(response: Response, request: Request, user: User) -> None:
    response.set_cookie(
        COOKIE_NAME,
        create_token(user.id),
        max_age=TOKEN_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(request),
        path="/",
    )


@router.post("/register", response_model=UserOut)
def register(req: AuthRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    if os.getenv("REGISTRATION_OPEN", "true").lower() not in ("true", "1", "yes"):
        raise HTTPException(status_code=403, detail="Hiện tại chưa mở đăng ký tài khoản mới")

    invite = os.getenv("INVITE_CODE", "").strip()
    if invite and (req.invite_code or "").strip() != invite:
        raise HTTPException(status_code=403, detail="Mã mời không đúng")

    email = req.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Email không hợp lệ")
    if len(req.password) < 8:
        raise HTTPException(status_code=422, detail="Mật khẩu phải có ít nhất 8 ký tự")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="Email này đã được đăng ký")

    is_first = db.query(User).count() == 0
    user = User(email=email, password_hash=hash_password(req.password), is_admin=is_first)
    db.add(user)
    db.commit()
    db.refresh(user)

    if is_first:
        # Vaults created before accounts existed belong to the first (admin) account
        db.query(Vault).filter(Vault.user_id.is_(None)).update({Vault.user_id: user.id})
        db.commit()

    _set_session(response, request, user)
    return user


@router.post("/login", response_model=UserOut)
def login(req: AuthRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    key = f"{request.client.host if request.client else '?'}|{email}"
    if _blocked(key):
        raise HTTPException(status_code=429, detail="Đăng nhập sai quá nhiều lần. Vui lòng thử lại sau 15 phút")

    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(req.password, user.password_hash):
        _failures.setdefault(key, []).append(time.time())
        raise HTTPException(status_code=401, detail="Email hoặc mật khẩu không đúng")
    if user.is_disabled:
        raise HTTPException(status_code=403, detail="Tài khoản đã bị khóa")

    _failures.pop(key, None)
    _set_session(response, request, user)
    return user


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"status": "success"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/config")
def public_config():
    """Tells the login screen whether sign-up needs an invite code."""
    return {
        "registration_open": os.getenv("REGISTRATION_OPEN", "true").lower() in ("true", "1", "yes"),
        "invite_required": bool(os.getenv("INVITE_CODE", "").strip()),
    }
