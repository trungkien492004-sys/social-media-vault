from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, HttpUrl

class ExtractRequest(BaseModel):
    url: str = Field(..., description="Profile or Post URL from Facebook, Instagram, Threads, TikTok, Zalo")
    custom_name: str = Field(..., min_length=1, max_length=100, description="Custom owner name or title")
    notes: Optional[str] = Field(None, max_length=500, description="Optional notes or tags")
    media_type: str = Field("all", pattern="^(all|image|video)$", description="Media format filter")
    max_items: Optional[int] = Field(30, ge=1, le=150, description="Maximum number of media items to download")

class AuthRequest(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=1, max_length=200)
    invite_code: Optional[str] = Field(None, max_length=100)

class UserOut(BaseModel):
    id: int
    email: str
    is_admin: bool

    class Config:
        from_attributes = True

class AdminUserOut(BaseModel):
    id: int
    email: str
    is_admin: bool
    is_disabled: bool
    created_at: datetime
    vault_count: int = 0
    item_count: int = 0
    size_bytes: int = 0

class BatchExtractRequest(BaseModel):
    urls: List[str] = Field(..., min_length=1, max_length=30, description="Many links, one task each")
    custom_name: Optional[str] = Field(None, max_length=100, description="Optional name prefix; auto-generated per link when empty")
    notes: Optional[str] = Field(None, max_length=500)
    media_type: str = Field("all", pattern="^(all|image|video)$")
    max_items: Optional[int] = Field(30, ge=1, le=150)

class SourceExtractRequest(BaseModel):
    html: str = Field(..., min_length=200, max_length=15_000_000, description="Page source copied from a logged-in browser")
    custom_name: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = Field(None, max_length=500)
    media_type: str = Field("all", pattern="^(all|image|video)$")
    max_items: Optional[int] = Field(30, ge=1, le=150)

class BatchTaskResponse(BaseModel):
    tasks: List["TaskResponse"]

class MediaItemOut(BaseModel):
    id: int
    vault_id: int
    file_type: str
    file_name: str
    file_path: str
    file_size: int
    original_url: Optional[str] = None
    caption: Optional[str] = None
    thumbnail_url: Optional[str] = None
    file_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class VaultOut(BaseModel):
    id: int
    custom_name: str
    platform: str
    profile_url: str
    notes: Optional[str] = None
    media_type_filter: str
    folder_name: str
    user_id: Optional[int] = None
    status: str
    error_message: Optional[str] = None
    total_items: int
    total_images: int
    total_videos: int
    total_size_bytes: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class VaultDetailOut(VaultOut):
    media_items: List[MediaItemOut] = []

class TaskResponse(BaseModel):
    task_id: str
    vault_id: int
    status: str
    message: str

class CookieStatus(BaseModel):
    exists: bool
    size_bytes: int
    platforms_detected: List[str]
    last_modified: Optional[str] = None
