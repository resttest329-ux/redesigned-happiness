from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    JWT_SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_IN_MINUTES: int = 480
    API_KEY: Optional[str] = None
    CLIENT_SECRET: Optional[str] = None
    FRONTEND_URL: Optional[str] = "http://127.0.0.1:5000"
    BASE_URL: str = "https://eivc-k6z6d.ondigitalocean.app"
    PASCA_BASE_URL: str = "https://test-api.pasca.co"


settings = Settings()