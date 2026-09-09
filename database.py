import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://u_hPcMes:CnJtnSaxc6Uz@sql.freedb.tech:3306/freedb_Sh0rGH8z"
)

from sqlalchemy.pool import NullPool

# Use NullPool to open and immediately close connections on request completion, avoiding connection leaks
engine = create_engine(
    DATABASE_URL,
    poolclass=NullPool,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
