import os
from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    APP_NAME: str = "Social Media Media Vault"
    HOST: str = "0.0.0.0"
    PORT: int = int(os.getenv("PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "False").lower() in ("true", "1")
    
    # Storage Paths
    BASE_DIR: Path = BASE_DIR
    DATA_DIR: Path = BASE_DIR / "data"
    VAULT_DIR: Path = BASE_DIR / "vault"
    COOKIES_DIR: Path = BASE_DIR / "cookies"
    COOKIES_FILE: Path = BASE_DIR / "cookies" / "cookies.txt"
    
    # Database
    DATABASE_URL: str = f"sqlite:///{BASE_DIR}/data/vault.db"
    
    # Optional persistent storage (Supabase). Leave empty to keep everything on local disk.
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""
    SUPABASE_BUCKET: str = "vault"

    # Extraction Limits & Rate Limiting
    MAX_ITEMS_PER_TASK: int = 100
    RATE_LIMIT_DELAY_MIN: float = 0.5
    RATE_LIMIT_DELAY_MAX: float = 1.8
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

# Ensure directories exist
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)
settings.COOKIES_DIR.mkdir(parents=True, exist_ok=True)
