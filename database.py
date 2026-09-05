import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://u_hPcMes:CnJtnSaxc6Uz@sql.freedb.tech:3306/freedb_Sh0rGH8z"
)

# Pool recycle & pre_ping to handle MySQL disconnects / idle timeouts on remote server
engine = create_engine(
    DATABASE_URL,
    pool_recycle=300,
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
