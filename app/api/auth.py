"""Login / logout / current-user endpoints and the auth dependency."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import User
from app.db.session import get_db
from app.services.audit import log_action
from app.services.security import (
    SESSION_MAX_AGE_SECONDS,
    create_session_token,
    hash_password,
    read_session_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_COOKIE = "air_session"


_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def enforce_can_edit(request: Request, db: Session = Depends(get_db)) -> None:
    """Global guard: reject data-changing requests from read-only accounts.

    Registered as an app-wide dependency. Only write methods on `/api/*` are
    checked, and `/api/auth/*` (login, logout, change own password) stays open so
    a read-only user can still sign in and manage their own account.
    """
    if request.method not in _WRITE_METHODS:
        return
    path = request.url.path
    if not path.startswith("/api/") or path.startswith("/api/auth/"):
        return
    token = request.cookies.get(SESSION_COOKIE)
    user_id = read_session_token(token) if token else None
    if user_id is None:
        return  # unauthenticated writes are handled by the endpoint's own guard
    user = db.get(User, user_id)
    if user is not None and not user.can_edit:
        raise HTTPException(
            status_code=403,
            detail="Account in sola lettura: non puoi modificare i dati.")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Dependency: resolve the logged-in user from the session cookie or 401."""
    token = request.cookies.get(SESSION_COOKIE)
    user_id = read_session_token(token) if token else None
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.get(User, user_id)
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail="Invalid or disabled user")
    return user


class LoginRequest(BaseModel):
    username: str
    password: str


class UserInfo(BaseModel):
    user_id: int
    username: str
    is_admin: bool
    can_edit: bool


@router.post("/login", response_model=UserInfo)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> UserInfo:
    user = db.query(User).filter(User.username == body.username).one_or_none()
    if user is None or not user.active or not verify_password(body.password, user.password_hash):
        # Same message for wrong user / wrong password: no username probing.
        raise HTTPException(status_code=401, detail="Invalid credentials")
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user.user_id),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    log_action(db, user, "login", "user_account", user.user_id)
    db.commit()
    return UserInfo(user_id=user.user_id, username=user.username,
                    is_admin=user.is_admin, can_edit=user.can_edit)


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE, samesite="lax", secure=settings.cookie_secure)
    return {"status": "ok"}


@router.get("/me", response_model=UserInfo)
def me(user: User = Depends(get_current_user)) -> UserInfo:
    return UserInfo(user_id=user.user_id, username=user.username,
                    is_admin=user.is_admin, can_edit=user.can_edit)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change_password")
def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is wrong")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    db_user = db.get(User, user.user_id)
    db_user.password_hash = hash_password(body.new_password)
    log_action(db, db_user, "update", "user_account", db_user.user_id,
               {"password": "cambiata"})
    db.commit()
    return {"status": "ok"}