import requests
import logging

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
    def __init__(self):
        self.http = requests.Session()
        self.http.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TSRDownloader/2.0"
        )
        self.authenticated = False
        self.member_id = ""
        self.login_key = ""

    def login(self, email: str, password: str) -> bool:
        """Inicio de sesión mediante GraphQL. Devuelve True si tiene éxito."""
        try:
            r = self.http.post(
                GRAPHQL_URL,
                json={"query": LOGIN_MUTATION, "variables": {"user": email, "password": password}},
            )
            data = r.json()

            if "errors" in data:
                msg = data["errors"][0].get("extensions", {}).get("reason", data["errors"][0]["message"])
                logger.error(f"Error de inicio de sesión: {msg}")
                return False

            resp = data["data"]["login"]
            if resp.get("need_verify"):
                logger.error("La cuenta requiere verificación por correo")
                return False

            member = resp["member"]
            self.member_id = str(member["MemberID"])
            self.login_key = member["session"]["SessionId"]
            self.authenticated = True
            self._set_auth_cookies()
            logger.info(f"Sesión iniciada como miembro #{self.member_id}")
            return True

        except Exception as e:
            logger.error(f"Error de inicio de sesión: {e}")
            return False

    def validate_saved(self, saved: dict) -> bool:
        """Valida una sesión guardada previamente."""
        if saved.get("authenticated"):
            self.member_id = saved["member_id"]
            self.login_key = saved["login_key"]
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

    def to_dict(self) -> dict:
        return {
            "authenticated": self.authenticated,
            "member_id": self.member_id,
            "login_key": self.login_key,
        }

    def _set_auth_cookies(self):
        self.http.cookies.set("LoginKey", self.login_key, domain=".thesimsresource.com")
        self.http.cookies.set("MemberID", self.member_id, domain=".thesimsresource.com")
