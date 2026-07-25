from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from sandbox.agents.llm_gateway import LLMGateway
from sandbox.agents.providers.deepseek import DeepSeekProviderAdapter
from sandbox.agents.providers.openai import OpenAIProviderAdapter
from sandbox.api.routes import router
from sandbox.app.settings import Settings
from sandbox.control.initialization import FinalizedSnapshotFileProvider, Initializer, InjectiveHolderDataProvider
from sandbox.control.run_manager import RunManager
from sandbox.core.errors import ConflictError, SandboxError
from sandbox.store.archive import ArchiveService
from sandbox.store.sqlite import SQLiteStore


settings = Settings.from_environment()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_directories()
    store = SQLiteStore(settings.database_path)
    archive_service = ArchiveService(store, settings.runtime_version)
    openai_adapter = OpenAIProviderAdapter(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.openai_model,
        timeout_seconds=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
        max_in_flight=settings.openai_max_in_flight,
        max_output_tokens=settings.openai_max_output_tokens,
    )
    deepseek_adapter = DeepSeekProviderAdapter(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        timeout_seconds=settings.deepseek_timeout_seconds,
        max_retries=settings.deepseek_max_retries,
        max_in_flight=settings.deepseek_max_in_flight,
        max_output_tokens=settings.deepseek_max_output_tokens,
    )
    gateway = LLMGateway(
        adapters={"openai": openai_adapter, "deepseek": deepseek_adapter},
        max_in_flight=max(settings.openai_max_in_flight, settings.deepseek_max_in_flight),
    )
    holder_providers = {}
    if settings.holder_snapshot_path is not None:
        holder_providers[settings.holder_snapshot_chain_id] = FinalizedSnapshotFileProvider(
            path=settings.holder_snapshot_path,
            chain_id=settings.holder_snapshot_chain_id,
        )
    if settings.injective_token_address is not None:
        holder_providers["injective"] = InjectiveHolderDataProvider(
            chain_id="injective",
            token_address=settings.injective_token_address,
            rpc_url=settings.injective_rpc_url,
            start_block=settings.injective_holder_start_block,
        )
    initializer = Initializer(holder_providers=holder_providers, llm_gateway=gateway)
    app.state.settings = settings
    app.state.store = store
    app.state.llm_gateway = gateway
    app.state.manager = RunManager(store, initializer, archive_service, settings.runtime_version)
    app.state.manager.recover_interrupted_branches()
    app.state.session_token = secrets.token_urlsafe(32)
    yield
    app.state.manager.close()
    store.close()


app = FastAPI(title="Parallel Market Sandbox", version=settings.runtime_version, lifespan=lifespan)


@app.middleware("http")
async def local_session(request: Request, call_next):
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        return JSONResponse(status_code=403, content={"error_code": "REMOTE_MODE_DISABLED", "message": "Framework Alpha only accepts loopback clients", "field_path": None, "retryable": False, "command_id": None})
    origin = request.headers.get("origin")
    if origin and request.method not in {"GET", "HEAD", "OPTIONS"}:
        parsed_origin = urlsplit(origin)
        expected_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if parsed_origin.scheme not in {"http", "https"} or origin.rstrip("/") != expected_origin.rstrip("/"):
            return JSONResponse(status_code=403, content={"error_code": "CROSS_ORIGIN_REJECTED", "message": "state-changing requests must be same-origin", "field_path": None, "retryable": False, "command_id": None})
    token = getattr(request.app.state, "session_token", None)
    supplied = request.cookies.get("sandbox_session")
    stale_session = token is not None and supplied is not None and supplied != token
    if request.url.path.startswith("/api/") and stale_session and request.method not in {"GET", "HEAD", "OPTIONS"}:
        response = JSONResponse(status_code=403, content={"error_code": "INVALID_SESSION", "message": "local session changed; refresh and retry", "field_path": None, "retryable": True, "command_id": None})
        response.set_cookie("sandbox_session", token, httponly=True, samesite="strict")
        return response
    response = await call_next(request)
    if token and supplied != token:
        response.set_cookie("sandbox_session", token, httponly=True, samesite="strict")
    return response


@app.exception_handler(SandboxError)
async def sandbox_error_handler(request: Request, error: SandboxError):
    status_code = 404 if error.error_code == "NOT_FOUND" else 409 if isinstance(error, ConflictError) else 422
    return JSONResponse(status_code=status_code, content={"error_code": error.error_code, "message": error.message, "field_path": error.field_path, "retryable": error.retryable, "command_id": request.headers.get("X-Command-ID"), "details": error.details})


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, error: RequestValidationError):
    first = error.errors()[0] if error.errors() else {}
    return JSONResponse(status_code=422, content={"error_code": "VALIDATION_FAILED", "message": first.get("msg", "request validation failed"), "field_path": ".".join(str(part) for part in first.get("loc", [])), "retryable": False, "command_id": request.headers.get("X-Command-ID")})


app.include_router(router)

if settings.frontend_dist.exists():
    assets = settings.frontend_dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}")
    async def frontend(path: str):
        candidate = settings.frontend_dist / path
        if path and candidate.is_file() and settings.frontend_dist in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(settings.frontend_dist / "index.html")
else:
    @app.get("/")
    async def no_frontend():
        return {"service": "parallel-market-sandbox", "message": "Build frontend with `npm run build` in frontend/."}
