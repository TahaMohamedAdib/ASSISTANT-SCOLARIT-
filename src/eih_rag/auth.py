"""Authentification minimale : un mot de passe administrateur unique (.env).

Limite assumee (voir README) : il n'y a pas de comptes individuels. Les
etudiants utilisent l'assistant sans connexion ; seul l'administrateur peut
modifier le corpus officiel ou consulter les retours. Le jeton est signe par
HMAC-SHA256 et expire apres ``ttl`` secondes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Header, HTTPException


class AdminAuth:
    def __init__(self, password: str, secret: str, ttl: int = 12 * 3600) -> None:
        self.password = password
        # Sans AUTH_SECRET, un secret aleatoire est genere : les jetons expirent au redemarrage.
        self.secret = (secret or secrets.token_hex(32)).encode()
        self.ttl = ttl

    @property
    def enabled(self) -> bool:
        return bool(self.password)

    def _sign(self, body: bytes) -> str:
        return base64.urlsafe_b64encode(hmac.new(self.secret, body, hashlib.sha256).digest()).decode().rstrip("=")

    def login(self, password: str) -> str:
        if not self.enabled or not hmac.compare_digest(password.encode(), self.password.encode()):
            raise HTTPException(status_code=401, detail="Mot de passe administrateur incorrect.")
        body = base64.urlsafe_b64encode(json.dumps({"role": "admin", "exp": int(time.time()) + self.ttl}).encode())
        return f"{body.decode().rstrip('=')}.{self._sign(body.rstrip(b'='))}"

    def role(self, token: str | None) -> str:
        if not token or "." not in token:
            return "student"
        body, signature = token.rsplit(".", 1)
        if not hmac.compare_digest(signature, self._sign(body.encode())):
            return "student"
        try:
            payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except (ValueError, json.JSONDecodeError):
            return "student"
        return "admin" if payload.get("role") == "admin" and payload.get("exp", 0) > time.time() else "student"

    def dependency(self):
        """Dependance FastAPI : 401 si l'appelant n'est pas administrateur."""

        def require_admin(authorization: str | None = Header(default=None)) -> str:
            token = authorization.removeprefix("Bearer ").strip() if authorization else None
            if self.role(token) != "admin":
                raise HTTPException(status_code=401, detail="Action réservée à l'administration.")
            return "admin"

        return require_admin
