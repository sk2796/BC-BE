import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

DEFAULT_DATABASE_URL = "mysql+pymysql://u_jy35gf:ByuvJzz2WM6o@sql.freedb.tech:3306/freedb_iks0U6hq"

DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
if not DATABASE_URL:
    DATABASE_URL = DEFAULT_DATABASE_URL

# SQLAlchemy 1.4+ compatibility for Render PostgreSQL URLs (postgres:// -> postgresql://)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)


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
