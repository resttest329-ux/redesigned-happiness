import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from datetime import datetime, timezone

from utils.database import engine, SessionLocal
from utils.models import SessionState
from utils.utility import close_client
from routes.auth_routes import router as auth_router
from routes.lookup_routes import router as lookup_router
from routes.customer_routes import router as customer_router
from routes.invoice_log_routes import router as invoice_log_router
from routes.session_routes import router as session_router
from routes.invoice_routes import router as invoice_router
from routes.item_routes import router as item_router

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection verified.")
    except Exception as e:
        logging.exception("Unexpected error")
        logger.error(f"Database connection failed: {e}")
        raise
    with SessionLocal() as db:
        expired_cutoff = datetime.now(timezone.utc).isoformat()
        db.query(SessionState).filter(
            SessionState.expires_at < expired_cutoff
        ).delete()
        db.commit()
        logger.info("Cleaned up expired sessions.")
    yield
    await close_client()


app = FastAPI(title="Zetamind e-Invoicing API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_URL", "http://127.0.0.1:5000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(lookup_router)
app.include_router(customer_router)
app.include_router(invoice_log_router)
app.include_router(session_router)
app.include_router(invoice_router)
app.include_router(item_router)


@app.get("/")
def root():
    return {"message": "Zetamind e-invoicing"}
