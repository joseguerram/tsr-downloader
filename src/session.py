"""Inicio de sesión con TSR mediante GraphQL (sin captcha)."""

from __future__ import annotations

import logging
from typing import Any, cast

import requests

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://api.thesimsresource.com/graphql"
LOGIN_MUTATION = """
mutation login($user: String!, $password: String!) {
    login(user: $user, password: $password) {
        member {
            MemberID
            session { SessionId }
        }
        need_verify
    }
}
"""


class TSRSession:
    def __init__(self) -> None:
        self.http = requests.Session()
        self.http.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TSRDownloader/2.0"
        )
        self.authenticated = False
        self.member_id = ""
        self.login_key = ""

    def login(self, email: str, password: str) -> str | None:
        """Inicio de sesión mediante GraphQL.

        Devuelve ``None`` si tiene éxito o, en caso contrario, el motivo
        del fallo para que lo muestre la capa de presentación.
        """
        try:
            r = self.http.post(
                GRAPHQL_URL,
                json={"query": LOGIN_MUTATION, "variables": {"user": email, "password": password}},
                timeout=15,
            )
            data = r.json()

            if "errors" in data:
                error = data["errors"][0]
                msg = error.get("extensions", {}).get("reason", error["message"])
                logger.error(f"Error de inicio de sesión: {msg}")
                return str(msg)

            resp = data["data"]["login"]
            if resp.get("need_verify"):
                logger.error("La cuenta requiere verificación por correo")
                return "la cuenta requiere verificación por correo (hazlo antes en la web)"

            member = resp["member"]
            self.member_id = str(member["MemberID"])
            self.login_key = member["session"]["SessionId"]
            self.authenticated = True
            self._set_auth_cookies()
            logger.info(f"Sesión iniciada como miembro #{self.member_id}")
            return None

        except requests.RequestException as e:
            logger.error(f"Sin conexión con TSR: {e}")
            return f"sin conexión con TSR ({type(e).__name__})"
        except Exception as e:
            logger.error(f"Respuesta inesperada al iniciar sesión: {e}")
            return f"respuesta inesperada de TSR ({type(e).__name__})"

    def validate_saved(self, saved: dict[str, Any]) -> bool:
        """Valida una sesión guardada previamente."""
        if saved.get("authenticated"):
            self.member_id = cast(str, saved["member_id"])
            self.login_key = cast(str, saved["login_key"])
            self.authenticated = True
            self._set_auth_cookies()
            try:
                r = self.http.get("https://www.thesimsresource.com/account/", timeout=10)
                if "/account/login" not in r.url:
                    logger.info("Sesión restaurada correctamente")
                    return True
            except requests.RequestException:
                pass
            self.authenticated = False
            return False
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "authenticated": self.authenticated,
            "member_id": self.member_id,
            "login_key": self.login_key,
        }

    def _set_auth_cookies(self) -> None:
        self.http.cookies.set("LoginKey", self.login_key, domain=".thesimsresource.com")
        self.http.cookies.set("MemberID", self.member_id, domain=".thesimsresource.com")
