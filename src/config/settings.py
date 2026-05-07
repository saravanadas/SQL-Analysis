import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """
    Centralized configuration management using Pydantic.
    Automatically loads from environment variables or .env file.
    """

    # =========================
    # SQL Server settings
    # =========================
    sql_server_host: str = Field(..., env="SQL_SERVER_HOST")
    sql_server_port: int = Field(1433, env="SQL_SERVER_PORT")  # ✅ changed to int
    sql_server_db: str = Field(..., env="SQL_SERVER_DB")
    sql_server_user: str = Field(..., env="SQL_SERVER_USER")
    sql_server_password: str = Field(..., env="SQL_SERVER_PASSWORD")
    db_driver: str = Field("ODBC Driver 18 for SQL Server", env="DB_DRIVER")

    # =========================
    # Railway Staging DB
    # =========================
    railway_db_url: str = Field(..., env="RAILWAY_DB_URL")

    # =========================
    # SharePoint Configuration
    # =========================
    sp_tenant_id: str = Field(..., env="SP_TENANT_ID")
    sp_client_id: str = Field(..., env="SP_CLIENT_ID")
    sp_client_secret: str = Field(..., env="SP_CLIENT_SECRET")
    sp_site_id: str = Field(..., env="SP_SITE_ID")
    sp_drive_id: str = Field(..., env="SP_DRIVE_ID")

    # =========================
    # Application Config
    # =========================
    log_level: str = Field("INFO", env="LOG_LEVEL")
    output_dir: str = Field("/app/output_files", env="OUTPUT_DIR")
    app_base_url: str = Field("http://localhost:8000", env="APP_BASE_URL")

    # =========================
    # Timeout / sizing policy
    # =========================
    http_request_timeout_seconds: int = Field(60, env="HTTP_REQUEST_TIMEOUT_SECONDS")
    sql_server_connect_timeout_seconds: int = Field(10, env="SQL_SERVER_CONNECT_TIMEOUT_SECONDS")
    sql_server_login_timeout_seconds: int = Field(10, env="SQL_SERVER_LOGIN_TIMEOUT_SECONDS")
    sql_server_pool_timeout_seconds: int = Field(30, env="SQL_SERVER_POOL_TIMEOUT_SECONDS")
    sql_server_preview_timeout_seconds: int = Field(30, env="SQL_SERVER_PREVIEW_TIMEOUT_SECONDS")
    sql_server_extract_timeout_seconds: int = Field(300, env="SQL_SERVER_EXTRACT_TIMEOUT_SECONDS")
    sql_server_force_abort_seconds: int = Field(0, env="SQL_SERVER_FORCE_ABORT_SECONDS")
    railway_connect_timeout_seconds: int = Field(10, env="RAILWAY_CONNECT_TIMEOUT_SECONDS")
    railway_query_statement_timeout_ms: int = Field(30000, env="RAILWAY_QUERY_STATEMENT_TIMEOUT_MS")
    railway_export_statement_timeout_ms: int = Field(0, env="RAILWAY_EXPORT_STATEMENT_TIMEOUT_MS")
    railway_insert_chunksize: int = Field(500, env="RAILWAY_INSERT_CHUNKSIZE")

    # =========================
    # Security (NEW)
    # =========================
    download_token_secret: str = Field(..., env="DOWNLOAD_TOKEN_SECRET")

    # =========================
    # VALIDATIONS
    # =========================

    @field_validator("sql_server_host", "sql_server_db", "sql_server_user")
    @classmethod
    def validate_sql_fields(cls, v):
        if not v or not v.strip():
            raise ValueError("SQL Server config cannot be empty")
        return v

    @field_validator("railway_db_url")
    @classmethod
    def validate_railway_url(cls, v):
        if not v.startswith("postgresql://"):
            raise ValueError("RAILWAY_DB_URL must be a valid PostgreSQL URL")
        return v

    @field_validator("sp_tenant_id", "sp_client_id", "sp_client_secret", "sp_site_id")
    @classmethod
    def validate_sharepoint_fields(cls, v):
        if not v or not v.strip():
            raise ValueError("SharePoint config cannot be empty")
        return v

    @field_validator("output_dir")
    @classmethod
    def validate_output_dir(cls, v):
        if not v:
            raise ValueError("OUTPUT_DIR must be set")
        return v

    @field_validator("download_token_secret")
    @classmethod
    def validate_secret(cls, v):
        if len(v) < 10:
            raise ValueError("DOWNLOAD_TOKEN_SECRET must be at least 10 characters long")
        return v

    @field_validator(
        "http_request_timeout_seconds",
        "sql_server_connect_timeout_seconds",
        "sql_server_login_timeout_seconds",
        "sql_server_pool_timeout_seconds",
        "sql_server_preview_timeout_seconds",
        "sql_server_extract_timeout_seconds",
        "sql_server_force_abort_seconds",
        "railway_connect_timeout_seconds",
        "railway_query_statement_timeout_ms",
        "railway_export_statement_timeout_ms",
        "railway_insert_chunksize",
    )
    @classmethod
    def validate_non_negative_ints(cls, v):
        if v < 0:
            raise ValueError("Timeout and chunk settings cannot be negative")
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


# Singleton instance of settings
settings = Settings()

print("Loaded Railway DB URL:", settings.railway_db_url[:30], "...")
