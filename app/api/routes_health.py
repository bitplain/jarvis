from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    probe = getattr(request.app.state, "ready_probe", None)
    result: dict[str, bool]
    if probe is None:
        result = await request.app.state.default_ready_probe()
    else:
        result = await probe()
    ready_status = all(result.values())
    body: dict[str, Any] = {
        "status": "ok" if ready_status else "degraded",
        "checks": result,
    }
    return JSONResponse(
        body,
        status_code=status.HTTP_200_OK if ready_status else status.HTTP_503_SERVICE_UNAVAILABLE,
    )
