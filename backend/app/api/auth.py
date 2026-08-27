from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User
from app.schemas import LoginRequest, TokenResponse, UserOut
from app.security import authenticate, create_access_token, get_current_user, limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])


@limiter.limit(settings.auth_rate_limit)
def _enforce_login_rate_limit(request: Request) -> None:
    """Raise RateLimitExceeded once this client is over the login limit.

    Called from the handler rather than decorating it: slowapi wraps the
    endpoint with functools.wraps, and FastAPI then resolves this module's
    postponed annotations against slowapi's globals, where they do not exist.
    """


@router.post("/login", response_model=TokenResponse)
def login(
    request: Request, payload: LoginRequest, db: Session = Depends(get_db)
) -> TokenResponse:
    """Rate limited: this is the one unauthenticated door into the dashboard."""
    _enforce_login_rate_limit(request=request)
    user = authenticate(db, payload.email, payload.password)
    if user is None:
        # Deliberately vague: never reveal whether the address exists.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )
    db.commit()
    return TokenResponse(
        access_token=create_access_token(user.email),
        expires_in_minutes=settings.jwt_ttl_minutes,
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
