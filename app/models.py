from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    is_disabled = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Vault(Base):
    __tablename__ = "vaults"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, nullable=True, index=True)  # owner; NULL only for pre-accounts data
    custom_name = Column(String(255), nullable=False, index=True)
    platform = Column(String(50), nullable=False, index=True)
    profile_url = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)
    media_type_filter = Column(String(20), default="all")  # all, image, video
    folder_name = Column(String(255), nullable=False)
    folder_path = Column(String(500), nullable=False)
    status = Column(String(50), default="pending", index=True)  # pending, downloading, completed, error
    error_message = Column(Text, nullable=True)
    
    total_items = Column(Integer, default=0)
    total_images = Column(Integer, default=0)
    total_videos = Column(Integer, default=0)
    total_size_bytes = Column(BigInteger, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    media_items = relationship("MediaItem", back_populates="vault", cascade="all, delete-orphan", order_by="desc(MediaItem.id)")


class MediaItem(Base):
    __tablename__ = "media_items"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    vault_id = Column(Integer, ForeignKey("vaults.id", ondelete="CASCADE"), nullable=False, index=True)
    file_type = Column(String(20), nullable=False)  # image, video
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)  # Relative to vault root, e.g. "vault_folder/001.mp4"
    file_size = Column(BigInteger, default=0)
    original_url = Column(Text, nullable=True)
    caption = Column(Text, nullable=True)
    thumbnail_url = Column(String(500), nullable=True)
    file_url = Column(String(1000), nullable=True)  # Public URL in persistent storage (Supabase), if enabled
    source_key = Column(String(1000), nullable=True, index=True)  # identity of the source media, used to skip re-downloads
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    vault = relationship("Vault", back_populates="media_items")


class AppSetting(Base):
    """Key/value store that survives restarts (used for cookies.txt on ephemeral hosts)."""
    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
