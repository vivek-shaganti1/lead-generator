"""Dashboard authentication: bcrypt passwords + short-lived JWTs."""
from __future__ import annotations

from datetime import timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import bcrypt
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.logging_config import get_logger
from app.models import User
from app.utils import utcnow

log = get_logger(__name__)

ALGORITHM = "HS256"
# The limiter lives here rather than in main.py so routers can decorate their
# endpoints without importing the application factory, which imports them.
# Disabled under ENV=test so the suite is not throttled by its own fixtures;
# tests that exercise throttling flip `limiter.enabled` themselves.
limiter = Limiter(
    key_func=get_remote_address, default_limits=[], enabled=settings.env != "test"
)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# bcrypt directly rather than through passlib: passlib 1.7.4 is unmaintained and
# reads bcrypt.__about__, which bcrypt >= 4.1 removed. It traps the error, so
# hashing still works, but every call logs a traceback. The output format is the
# same $2b$ string either way, so stored hashes keep verifying across the change.
BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    # bcrypt silently truncates past 72 bytes; refuse rather than surprise anyone.
    raw = password.encode()
    if len(raw) > 72:
        raise ValueError("password must be 72 bytes or fewer")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except (ValueError, TypeError):
        # Malformed or non-bcrypt hash in the column: treat as a failed login.
        return False


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    expire = utcnow() + timedelta(minutes=expires_minutes or settings.jwt_ttl_minutes)
    payload = {"sub": subject, "exp": expire, "iat": utcnow(), "typ": "access"}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return None


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.execute(
        select(User).where(User.email == email.strip().lower())
    ).scalars().first()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = utcnow()
    return user


def get_current_user(
    token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_error
    payload = decode_token(token)
    if not payload or not payload.get("sub"):
        raise credentials_error
    user = db.execute(
        select(User).where(User.email == payload["sub"])
    ).scalars().first()
    if user is None or not user.is_active:
        raise credentials_error
    return user


def ensure_admin_user(db: Session) -> User:
    """Seed the admin account from env, and keep its password in step with env.

    .env is the source of truth. Creating the user on first boot but then ignoring
    ADMIN_PASSWORD forever means an operator who rotates the password in .env,
    restarts, and cannot log in has no way to tell why — so rotate it here and say
    so in the log.
    """
    email = settings.admin_email.strip().lower()
    user = db.execute(select(User).where(User.email == email)).scalars().first()
    if user:
        if not verify_password(settings.admin_password, user.password_hash):
            user.password_hash = hash_password(settings.admin_password)
            log.info("admin.password_rotated_from_env", email=email)
        return user
    user = User(
        email=email, password_hash=hash_password(settings.admin_password), is_admin=True
    )
    db.add(user)
    db.flush()
    log.info("admin.created", email=email)
    return user
