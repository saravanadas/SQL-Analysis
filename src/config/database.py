from sqlalchemy import create_engine
from src.config.settings import settings

def get_engine():
    return create_engine(
        settings.railway_db_url,
        pool_pre_ping=True
    )
