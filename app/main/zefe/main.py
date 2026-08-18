from __future__ import annotations

import logging

from fasthtml.common import FastHTML, serve

from config import (
    HOST,
    PORT,
    RELOAD,
    SESSION_SECRET,
    STATIC_DIR,
)
from routes import (
    auth_routes,
    customer_routes,
    dashboard_routes,
    invoice_routes,
    item_routes,
    settings_routes,
    wizard_routes,
)
from services import api_client, auth_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("zefe")


async def lifespan(app):
    await api_client.startup()
    logger.info("zefe started, backend=%s", api_client.BACKEND_URL)
    try:
        yield
    finally:
        await api_client.shutdown()
        auth_service.shutdown()
        logger.info("zefe shutdown complete")


app = FastHTML(
    lifespan=lifespan,
    secret_key=SESSION_SECRET,
)

app.static_route_exts(prefix="/static/", static_path=str(STATIC_DIR))


def rt(path, methods=None, **kwargs):
    def decorator(func):
        app.route(path, methods=methods or ["GET"], **kwargs)(func)
        return func

    return decorator


auth_routes.register_routes(rt)
customer_routes.register_routes(rt)
dashboard_routes.register_routes(rt)
item_routes.register_routes(rt)
wizard_routes.register_routes(rt)
invoice_routes.register_routes(rt)
settings_routes.register_routes(rt)

if __name__ == "__main__":
    serve(host=HOST, port=PORT, reload=RELOAD)
