import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from foreman import mcp_server, web
from foreman.config import settings
from foreman.errors import ConflictError, NotFoundError
from foreman.service import ForemanService
from foreman.store import DynamoStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

store = DynamoStore(settings.table_name, settings.dynamodb_endpoint)
service = ForemanService(store)
mcp_server.configure(service)
web.configure(service)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    store.ensure_table()
    async with mcp_server.mcp.session_manager.run():
        yield


def handle_not_found(request: Request, exc: Exception) -> HTMLResponse:
    return web.render_error(request, 404, str(exc))


def handle_conflict(request: Request, exc: Exception) -> HTMLResponse:
    return web.render_error(request, 409, str(exc))


def handle_invalid_input(request: Request, exc: Exception) -> HTMLResponse:
    return web.render_error(request, 400, str(exc))


app = FastAPI(title="foreman", lifespan=lifespan)
app.add_exception_handler(NotFoundError, handle_not_found)
app.add_exception_handler(ConflictError, handle_conflict)
app.add_exception_handler(ValueError, handle_invalid_input)
app.mount("/static", StaticFiles(directory=web.PACKAGE_DIR / "static"), name="static")
app.include_router(web.router)
# Registering the SDK's own /mcp route avoids the /mcp -> /mcp/ redirect a sub-app mount forces.
app.router.routes.extend(mcp_server.mcp.streamable_http_app().routes)
