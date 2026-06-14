from typing import Annotated

from fastapi import Header, HTTPException, status


def require_admin_token(
    configured_token: str,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    if not configured_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin token is not configured",
        )
    expected = f"Bearer {configured_token}"
    if authorization != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
