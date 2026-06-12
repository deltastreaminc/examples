from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    signup_api_url: str = "https://demo.deltastream.io/api/signup"
    anthropic_base_url: str = "https://demo.deltastream.io/anthropic"
    deltastream_mcp_url: str = "https://api-kap822.deltastream.io/mcp/v2"
    insecure_demo_tls: bool = False

    model_name: str = "anthropic:claude-sonnet-4-6"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    query_limit: int = 250
    ops_mv_fqn: str = '"stablecoin_payment_demo"."public"."stablecoin_payment_ops_context_mv"'
    support_mv_fqn: str = '"stablecoin_payment_demo"."public"."support_case_summary_by_invoice_mv"'

    model_config = SettingsConfigDict(
        env_file=str(ROOT_ENV_PATH),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
