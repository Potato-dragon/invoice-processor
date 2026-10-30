"""FastAPI application: routes under /api, X-API-Key on everything except health."""
import logging
import os

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import documents, invoices, search
from app.api.deps import ApiError, require_api_key
from app.contracts import ErrorCode, PipelineError

logger = logging.getLogger(__name__)

app = FastAPI(title="Invoice AI API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.exception_handler(ApiError)
async def api_error(_: Request, exc: ApiError) -> JSONResponse:
    return _error(exc.status, exc.code, exc.message)


@app.exception_handler(PipelineError)
async def pipeline_error(_: Request, exc: PipelineError) -> JSONResponse:
    return _error(400, exc.code.value, exc.message)


_HTTP_CODES = {401: ErrorCode.UNAUTHORIZED, 404: ErrorCode.NOT_FOUND, 405: ErrorCode.BAD_REQUEST, 413: ErrorCode.FILE_TOO_LARGE,
               429: ErrorCode.RATE_LIMITED}


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_CODES.get(exc.status_code, ErrorCode.BAD_REQUEST if exc.status_code < 500 else ErrorCode.INTERNAL_ERROR)
    return _error(exc.status_code, code.value, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
    return _error(422, ErrorCode.BAD_REQUEST.value, f"{where}: {first.get('msg', 'invalid request')}")


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled API error")
    return _error(500, ErrorCode.INTERNAL_ERROR.value, "internal error")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


for module in (documents, invoices, search):
    app.include_router(module.router, prefix="/api", dependencies=[Depends(require_api_key)])
