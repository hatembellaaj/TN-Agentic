"""
Routes d'authentification.

API (/api/auth/*) :
  POST  /token               → JWT (OAuth2 password flow, utilisé par Swagger « Authorize »)
  GET   /me                  → profil courant
  POST  /me/password         → changement de mot de passe (révoque les autres jetons)
  POST  /logout-all          → révoque tous les jetons de l'utilisateur
  GET   /users               → liste (admin)
  POST  /users               → création (admin)
  PATCH /users/{id}          → rôle / activation / reset mot de passe (admin)

Dashboard :
  GET/POST /dashboard/login, POST /dashboard/logout
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import (
    SESSION_COOKIE,
    Principal,
    get_principal,
    require_admin,
    require_human,
    safe_next,
)
from app.auth.ratelimit import login_limiter
from app.auth.security import (
    create_access_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.config import settings
from app.db import get_session
from app.models import User

logger = logging.getLogger("app.auth")

api_router = APIRouter(prefix="/auth", tags=["auth"])
dashboard_auth_router = APIRouter(prefix="/dashboard", include_in_schema=False)

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "dashboard" / "templates")
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _client_ip(request: Request) -> str:
    # Nginx est le seul point d'entrée et positionne X-Real-IP.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


def _authenticate(session: Session, request: Request, username: str, password: str) -> User:
    key = f"{_client_ip(request)}|{username.lower()}"
    if login_limiter.is_blocked(key):
        logger.warning("login bloqué (rate limit) user=%s ip=%s", username, _client_ip(request))
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Trop de tentatives. Réessayez dans quelques minutes.")

    user = session.scalar(select(User).where(func.lower(User.username) == username.lower()))
    ok = verify_password(password, user.password_hash if user else None)
    if not ok or user is None or not user.is_active:
        login_limiter.register_failure(key)
        logger.warning("échec login user=%s ip=%s", username, _client_ip(request))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Identifiants invalides",
                            headers={"WWW-Authenticate": "Bearer"})

    login_limiter.reset(key)
    user.last_login_at = dt.datetime.now(dt.timezone.utc)
    session.commit()
    logger.info("login ok user=%s ip=%s", user.username, _client_ip(request))
    return user


def _token_for(user: User, minutes: int) -> str:
    return create_access_token(
        user_id=user.id, username=user.username, role=user.role,
        token_version=user.token_version, expires_minutes=minutes,
    )


# ------------------------------------------------------------------
# Schémas
# ------------------------------------------------------------------
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    id: int
    username: str
    email: str | None
    role: str
    is_active: bool
    last_login_at: dt.datetime | None

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str
    email: str | None = None
    role: Literal["admin", "editor"] = "editor"


class UserUpdate(BaseModel):
    role: Literal["admin", "editor"] | None = None
    is_active: bool | None = None
    password: str | None = None
    email: str | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


# ------------------------------------------------------------------
# API
# ------------------------------------------------------------------
@api_router.post("/token", response_model=TokenResponse, summary="Obtenir un jeton JWT")
def issue_token(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
) -> TokenResponse:
    """Échange identifiant / mot de passe contre un JWT Bearer (durée : ACCESS_TOKEN_EXPIRE_MINUTES)."""
    user = _authenticate(session, request, form.username, form.password)
    minutes = settings.ACCESS_TOKEN_EXPIRE_MINUTES
    return TokenResponse(access_token=_token_for(user, minutes), expires_in=minutes * 60)


@api_router.get("/me", response_model=UserOut)
def me(principal: Principal = Depends(require_human), session: Session = Depends(get_session)):
    return session.get(User, principal.user_id)


@api_router.post("/me/password", status_code=204, response_class=Response)
def change_password(
    payload: PasswordChange,
    principal: Principal = Depends(require_human),
    session: Session = Depends(get_session),
):
    user = session.get(User, principal.user_id)
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, "Mot de passe actuel incorrect")
    try:
        user.password_hash = hash_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    user.token_version += 1
    session.commit()
    return Response(status_code=204)


@api_router.post("/logout-all", status_code=204, response_class=Response)
def logout_all(principal: Principal = Depends(require_human), session: Session = Depends(get_session)):
    """Invalide tous les jetons et sessions déjà émis pour cet utilisateur."""
    user = session.get(User, principal.user_id)
    user.token_version += 1
    session.commit()
    return Response(status_code=204)


@api_router.get("/users", response_model=list[UserOut], dependencies=[Depends(require_admin)])
def list_users(session: Session = Depends(get_session)):
    return session.scalars(select(User).order_by(User.id)).all()


@api_router.post("/users", response_model=UserOut, status_code=201, dependencies=[Depends(require_admin)])
def create_user(payload: UserCreate, session: Session = Depends(get_session)):
    exists = session.scalar(select(User).where(func.lower(User.username) == payload.username.lower()))
    if exists:
        raise HTTPException(409, "Ce nom d'utilisateur existe déjà")
    try:
        pwd_hash = hash_password(payload.password)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    user = User(username=payload.username, email=payload.email, role=payload.role, password_hash=pwd_hash)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@api_router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    principal: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
):
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Utilisateur introuvable")
    if user.id == principal.user_id and (payload.is_active is False or payload.role == "editor"):
        raise HTTPException(400, "Impossible de vous désactiver ou de retirer votre propre rôle admin")
    revoke = False
    if payload.role is not None and payload.role != user.role:
        user.role, revoke = payload.role, True
    if payload.is_active is not None and payload.is_active != user.is_active:
        user.is_active, revoke = payload.is_active, True
    if payload.email is not None:
        user.email = payload.email
    if payload.password:
        try:
            user.password_hash = hash_password(payload.password)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        revoke = True
    if revoke:
        user.token_version += 1
    session.commit()
    session.refresh(user)
    return user


# ------------------------------------------------------------------
# Dashboard : login / logout
# ------------------------------------------------------------------
@dashboard_auth_router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str | None = None,
               principal: Principal | None = Depends(get_principal)):
    if principal is not None and principal.kind == "user":
        return RedirectResponse(safe_next(next), status_code=303)
    return templates.TemplateResponse(
        "login.html", {"request": request, "next": safe_next(next), "error": None}
    )


@dashboard_auth_router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/dashboard/"),
    session: Session = Depends(get_session),
):
    target = safe_next(next)
    try:
        user = _authenticate(session, request, username, password)
    except HTTPException as exc:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "next": target, "error": exc.detail, "username": username},
            status_code=exc.status_code,
        )

    minutes = settings.SESSION_EXPIRE_MINUTES
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        _token_for(user, minutes),
        max_age=minutes * 60,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="strict",
        path="/",
    )
    return response


@dashboard_auth_router.post("/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse("/dashboard/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True,
                           secure=settings.COOKIE_SECURE, samesite="strict")
    return response
