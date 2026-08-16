import logging
import os
import secrets
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic
from sqlalchemy import text
from datetime import datetime, timezone
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from utils.database import engine, SessionLocal
from utils.models import SessionState
from utils.utility import close_client
from config import settings
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


class DocsAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path not in {
            "/api/docs",
            "/api/docs/oauth2-redirect",
            "/api/openapi.json",
            "/api/redoc",
        }:
            return await call_next(request)

        credentials = HTTPBasic(auto_error=False)(request)
        if (
            not settings.DOCS_USERNAME
            or not settings.DOCS_PASSWORD
            or credentials is None
            or not secrets.compare_digest(
                credentials.username, settings.DOCS_USERNAME
            )
            or not secrets.compare_digest(
                credentials.password, settings.DOCS_PASSWORD
            )
        ):
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
                headers={"WWW-Authenticate": 'Basic realm="docs"'},
            )
        return await call_next(request)


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


IS_PRODUCTION = settings.ENVIRONMENT == "production"

app = FastAPI(
    title="Zetamind e-Invoicing API",
    lifespan=lifespan,
    openapi_url=None if IS_PRODUCTION else "/api/openapi.json",
    docs_url=None if IS_PRODUCTION else "/api/docs",
)

app.add_middleware(DocsAuthMiddleware)

if IS_PRODUCTION:
    logger.info("API docs and OpenAPI schema disabled — production environment")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_URL", "http://127.0.0.1:5000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(lookup_router, prefix="/api")
app.include_router(customer_router, prefix="/api")
app.include_router(invoice_log_router, prefix="/api")
app.include_router(session_router, prefix="/api")
app.include_router(invoice_router, prefix="/api")
app.include_router(item_router, prefix="/api")


@app.get("/")
def root():
    return {"message": "Zetamind e-invoicing"}
