"""
Gestion des comptes en ligne de commande.

    docker compose exec editorial-core python -m app.auth.cli create-user hatem --role admin
    docker compose exec editorial-core python -m app.auth.cli reset-password hatem
    docker compose exec editorial-core python -m app.auth.cli disable hatem
    docker compose exec editorial-core python -m app.auth.cli list
    docker compose exec editorial-core python -m app.auth.cli gen-api-key
"""
from __future__ import annotations

import argparse
import getpass
import secrets
import sys

from sqlalchemy import func, select

from app.auth.security import hash_password
from app.db import SessionLocal
from app.models import User


def _ask_password() -> str:
    while True:
        p1 = getpass.getpass("Mot de passe (12 caractères min.) : ")
        p2 = getpass.getpass("Confirmation : ")
        if p1 != p2:
            print("Les mots de passe ne correspondent pas.", file=sys.stderr)
            continue
        return p1


def _find(session, username: str) -> User:
    user = session.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if user is None:
        sys.exit(f"Utilisateur '{username}' introuvable.")
    return user


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.auth.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create-user")
    c.add_argument("username")
    c.add_argument("--role", choices=["admin", "editor"], default="editor")
    c.add_argument("--email")

    r = sub.add_parser("reset-password")
    r.add_argument("username")

    d = sub.add_parser("disable")
    d.add_argument("username")

    e = sub.add_parser("enable")
    e.add_argument("username")

    sub.add_parser("list")
    sub.add_parser("gen-api-key")

    args = parser.parse_args(argv)

    if args.cmd == "gen-api-key":
        print(secrets.token_urlsafe(48))
        return

    with SessionLocal() as session:
        if args.cmd == "create-user":
            if session.scalar(select(User).where(func.lower(User.username) == args.username.lower())):
                sys.exit(f"'{args.username}' existe déjà.")
            try:
                pwd_hash = hash_password(_ask_password())
            except ValueError as exc:
                sys.exit(str(exc))
            session.add(User(username=args.username, email=args.email, role=args.role, password_hash=pwd_hash))
            session.commit()
            print(f"✓ Utilisateur '{args.username}' créé (rôle {args.role}).")
        elif args.cmd == "reset-password":
            user = _find(session, args.username)
            try:
                user.password_hash = hash_password(_ask_password())
            except ValueError as exc:
                sys.exit(str(exc))
            user.token_version += 1
            session.commit()
            print("✓ Mot de passe changé, sessions existantes révoquées.")
        elif args.cmd in ("disable", "enable"):
            user = _find(session, args.username)
            user.is_active = args.cmd == "enable"
            user.token_version += 1
            session.commit()
            print(f"✓ '{user.username}' {'activé' if user.is_active else 'désactivé'}.")
        elif args.cmd == "list":
            for u in session.scalars(select(User).order_by(User.id)):
                state = "actif" if u.is_active else "désactivé"
                print(f"{u.id:>3}  {u.username:<24} {u.role:<7} {state:<10} dernier login: {u.last_login_at or '-'}")


if __name__ == "__main__":
    main()
