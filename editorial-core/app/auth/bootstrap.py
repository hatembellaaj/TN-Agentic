"""Création du premier compte admin au démarrage si la table users est vide."""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.auth.security import hash_password
from app.config import settings
from app.db import SessionLocal
from app.models import User

logger = logging.getLogger("app.auth")


def ensure_initial_admin() -> None:
    username = settings.INITIAL_ADMIN_USERNAME
    password = settings.INITIAL_ADMIN_PASSWORD
    try:
        with SessionLocal() as session:
            if (session.scalar(select(func.count(User.id))) or 0) > 0:
                return
            if not (username and password):
                logger.warning(
                    "Aucun utilisateur en base : créez un admin avec "
                    "`docker compose exec editorial-core python -m app.auth.cli create-user --role admin <login>` "
                    "ou définissez INITIAL_ADMIN_USERNAME / INITIAL_ADMIN_PASSWORD."
                )
                return
            session.add(User(username=username, password_hash=hash_password(password), role="admin"))
            session.commit()
            logger.info("Compte admin initial '%s' créé. Retirez INITIAL_ADMIN_PASSWORD du .env.", username)
    except SQLAlchemyError as exc:
        logger.warning("Bootstrap admin ignoré (migration 0004 appliquée ?) : %s", exc.__class__.__name__)
    except ValueError as exc:
        logger.error("INITIAL_ADMIN_PASSWORD refusé : %s", exc)
