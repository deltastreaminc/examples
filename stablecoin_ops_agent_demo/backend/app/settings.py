from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    anthropic_api_key: str
    deltastream_mcp_url: str
    deltastream_mcp_auth_token: str

    model_name: str = "anthropic:claude-sonnet-4-6"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    query_limit: int = 250
    ops_mv_fqn: str = "stablecoin.public.stablecoin_payment_ops_context_mv"

    model_config = SettingsConfigDict(
        env_file=str(ROOT_ENV_PATH),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
