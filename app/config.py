from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    direct_url: str = ""
    cors_origins: str = ""

    api_prefix: str = "/api/v1"
    max_upload_bytes: int = 4_500_000  # Vercel serverless request body ceiling

    rule_version: str = "m4-v0.1"
    qty_tolerance_abs: float = 0.0
    qty_tolerance_pct: float = 0.0
    price_tolerance_pct: float = 0.5
    tax_tolerance_abs: float = 1.0
    expected_tax_rate: float = 0.18
    auto_close_matched: bool = True

    @property
    def sqlalchemy_url(self) -> str:
        return _to_sqlalchemy_url(self.database_url)

    @property
    def sqlalchemy_direct_url(self) -> str:
        return _to_sqlalchemy_url(self.direct_url or self.database_url)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def default_tolerances(self) -> dict:
        return {
            "qty_tolerance_abs": self.qty_tolerance_abs,
            "qty_tolerance_pct": self.qty_tolerance_pct,
            "price_tolerance_pct": self.price_tolerance_pct,
            "tax_tolerance_abs": self.tax_tolerance_abs,
            "expected_tax_rate": self.expected_tax_rate,
            "auto_close_matched": self.auto_close_matched,
        }


def _to_sqlalchemy_url(url: str) -> str:
    # Neon hands out bare postgresql:// URLs; SQLAlchemy needs the psycopg3 driver
    # named explicitly or it reaches for psycopg2, which isn't installed.
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
