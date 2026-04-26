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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


# Singleton instance of settings
settings = Settings()
