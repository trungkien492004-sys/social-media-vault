from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, HttpUrl

class ExtractRequest(BaseModel):
    url: str = Field(..., description="Profile or Post URL from Facebook, Instagram, Threads, TikTok, Zalo")
    custom_name: str = Field(..., min_length=1, max_length=100, description="Custom owner name or title")
    notes: Optional[str] = Field(None, max_length=500, description="Optional notes or tags")
    media_type: str = Field("all", pattern="^(all|image|video)$", description="Media format filter")
    max_items: Optional[int] = Field(30, ge=1, le=150, description="Maximum number of media items to download")

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
