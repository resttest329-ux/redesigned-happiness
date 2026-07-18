import os
import logging
import httpx
import reflex as rx
from typing import Optional
from app.states.api_utils import normalize_detail


API_BASE = os.environ.get("ZEBE_API_BASE_URL", "http://127.0.0.1:8000")
SESSION_COOKIE = "zefe_session_id"


def normalize_detail(resp, default_msg: str) -> str:
    try:
        return resp.json().get("detail", default_msg)
    except Exception:
        logging.exception("Unexpected error")
        return default_msg


class AuthState(rx.State):
    # Session / token
    session_id: str = rx.Cookie(name=SESSION_COOKIE, max_age=60 * 60 * 8)
    access_token: str = ""

    # Current user
    user_id: int = 0
    username: str = ""
    email: str = ""
    business_id: str = ""
    service_id: str = ""
    is_authenticated: bool = False
    has_secret: bool = False

    # Profile fields
    tin: str = ""
    party_name: str = ""
    telephone: str = ""
    street_name: str = ""
    city_name: str = ""
    postal_zone: str = ""
    country: str = ""
    state_field: str = ""
    lga: str = ""
    certificate: str = ""
    public_key: str = ""

    # UI state
    loading: bool = False
    error_message: str = ""
    success_message: str = ""
    backend_unavailable: bool = False

    def _headers(self) -> dict:
        if self.access_token:
            return {"Authorization": f"Bearer {self.access_token}"}
        return {}

    async def _refresh_token(self) -> bool:
        if not self.session_id:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    f"{API_BASE}/auth/refresh",
                    json={"session_id": self.session_id},
                )
            if r.status_code == 200:
                data = r.json()
                self.access_token = data.get("access_token", "")
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        await client.patch(
                            f"{API_BASE}/sessions/{self.session_id}/token",
                            json={"jwt_token": self.access_token},
                        )
                except Exception:
                    logging.exception("Unexpected error")
                return True
        except Exception as e:
            logging.exception(f"refresh failed: {e}")
        return False

    async def _api_request(
        self, method: str, path: str, retry: bool = True, **kwargs
    ) -> Optional[httpx.Response]:
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.request(
                    method, f"{API_BASE}{path}", headers=headers, **kwargs
                )
            self.backend_unavailable = False
            if resp.status_code == 401 and retry and self.session_id:
                if await self._refresh_token():
                    return await self._api_request(
                        method, path, retry=False, headers=headers, **kwargs
                    )
            return resp
        except (
            httpx.ConnectError,
            httpx.TimeoutException,
            httpx.NetworkError,
        ) as e:
            logging.exception(f"backend unavailable: {e}")
            self.backend_unavailable = True
            self.error_message = (
                "Backend service unavailable. Please try again."
            )
            return None
        except Exception as e:
            logging.exception(f"api error: {e}")
            self.error_message = f"Request failed: {str(e)}"
            return None

    @rx.event
    async def check_session(self):
        self.error_message = ""
        self.success_message = ""
        if not self.session_id:
            self.is_authenticated = False
            yield rx.redirect("/login")
            return
        self.loading = True
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{API_BASE}/sessions/{self.session_id}")
            if r.status_code == 200:
                data = r.json()
                self.access_token = data.get("jwt_token", "")
                self.username = data.get("username", "")
                self.business_id = data.get("business_id", "")
                self.is_authenticated = True
                self.backend_unavailable = False
                yield AuthState.load_profile
            else:
                self.session_id = ""
                self.is_authenticated = False
                yield rx.redirect("/login")
        except (
            httpx.ConnectError,
            httpx.TimeoutException,
            httpx.NetworkError,
        ) as e:
            logging.exception(f"session check backend down: {e}")
            self.backend_unavailable = True
            self.is_authenticated = False
        except Exception as e:
            logging.exception(f"session check failed: {e}")
            self.backend_unavailable = True
            self.is_authenticated = False
        finally:
            self.loading = False

    @rx.event
    async def load_profile(self):
        if not self.access_token:
            return
        resp = await self._api_request("GET", "/auth/me")
        if resp is None:
            return
        if resp.status_code in (401, 403):
            self.session_id = ""
            self.access_token = ""
            self.is_authenticated = False
            self.user_id = 0
            self.username = ""
            self.email = ""
            self.business_id = ""
            self.has_secret = False
            self.error_message = normalize_detail(
                resp, "Your session is no longer valid. Please sign in again."
            )
            yield rx.redirect("/login")
            return
        if resp.status_code == 200:
            data = resp.json()
            self.user_id = data.get("id", 0)
            self.username = data.get("username", "")
            self.email = data.get("email", "")
            self.business_id = data.get("business_id", "")
            self.service_id = data.get("service_id", "")
            self.tin = data.get("tin") or ""
            self.party_name = data.get("party_name") or ""
            self.telephone = data.get("telephone") or ""
            self.street_name = data.get("street_name") or ""
            self.city_name = data.get("city_name") or ""
            self.postal_zone = data.get("postal_zone") or ""
            self.country = data.get("country") or ""
            self.state_field = data.get("state") or ""
            self.lga = data.get("lga") or ""
            self.certificate = data.get("certificate") or ""
            self.public_key = data.get("public_key") or ""
            self.is_authenticated = True
            secret_resp = await self._api_request("GET", "/auth/me/secret")
            if secret_resp is not None and secret_resp.status_code == 200:
                self.has_secret = secret_resp.json().get("has_secret", False)

    @rx.event
    async def login(self, form_data: dict):
        self.error_message = ""
        self.success_message = ""
        self.loading = True
        try:
            email = form_data.get("email", "").strip().lower()
            password = form_data.get("password", "")
            if not email or not password:
                self.error_message = "Please provide email and password."
                return
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    r = await client.post(
                        f"{API_BASE}/auth/token",
                        data={"username": email, "password": password},
                        headers={
                            "Content-Type": "application/x-www-form-urlencoded"
                        },
                    )
            except (
                httpx.ConnectError,
                httpx.TimeoutException,
                httpx.NetworkError,
            ) as e:
                logging.exception(f"login backend down: {e}")
                self.backend_unavailable = True
                self.error_message = "Backend service unavailable."
                return
            if r.status_code != 200:
                self.error_message = normalize_detail(r, "Login failed")
                return
            self.backend_unavailable = False
            token_data = r.json()
            self.access_token = token_data.get("access_token", "")
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    me = await client.get(
                        f"{API_BASE}/auth/me",
                        headers={
                            "Authorization": f"Bearer {self.access_token}"
                        },
                    )
                if me.status_code == 200:
                    user = me.json()
                    self.user_id = user.get("id", 0)
                    self.username = user.get("username", "")
                    self.business_id = user.get("business_id", "")
                else:
                    self.access_token = ""
                    self.error_message = normalize_detail(
                        me, "Failed to load user profile"
                    )
                    return
                async with httpx.AsyncClient(timeout=10.0) as client:
                    s = await client.post(
                        f"{API_BASE}/sessions",
                        json={
                            "jwt_token": self.access_token,
                            "user_secret": "",
                            "username": self.username,
                            "business_id": self.business_id,
                            "user_id": self.user_id,
                        },
                    )
                if s.status_code == 200:
                    new_session_id = s.json().get("session_id", "") or ""
                    if not new_session_id:
                        self.session_id = ""
                        self.access_token = ""
                        self.user_id = 0
                        self.username = ""
                        self.business_id = ""
                        self.is_authenticated = False
                        self.error_message = (
                            "Could not establish a session. Please try again."
                        )
                        return
                    self.session_id = new_session_id
                else:
                    self.access_token = ""
                    self.user_id = 0
                    self.username = ""
                    self.business_id = ""
                    self.error_message = normalize_detail(
                        s, "Could not establish a session. Please try again."
                    )
                    return
            except Exception as e:
                logging.exception(f"session create failed: {e}")
            if not self.session_id:
                self.is_authenticated = False
                self.error_message = (
                    "Could not establish a session. Please try again."
                )
                return
            self.is_authenticated = True
            yield AuthState.load_profile
            yield rx.redirect("/")
        finally:
            self.loading = False

    @rx.event
    async def register(self, form_data: dict):
        self.error_message = ""
        self.success_message = ""
        self.loading = True
        try:
            payload = {
                "username": form_data.get("username", "").strip(),
                "email": form_data.get("email", "").strip().lower(),
                "password": form_data.get("password", ""),
                "business_id": form_data.get("business_id", "").strip(),
                "service_id": form_data.get("service_id", "").strip(),
                "is_active": True,
            }
            if not all(
                [
                    payload["username"],
                    payload["email"],
                    payload["password"],
                    payload["business_id"],
                    payload["service_id"],
                ]
            ):
                self.error_message = "All fields are required."
                return
            if len(payload["password"]) < 8:
                self.error_message = "Password must be at least 8 characters."
                return
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    r = await client.post(
                        f"{API_BASE}/auth/register", json=payload
                    )
            except (
                httpx.ConnectError,
                httpx.TimeoutException,
                httpx.NetworkError,
            ) as e:
                logging.exception(f"register backend down: {e}")
                self.backend_unavailable = True
                self.error_message = "Backend service unavailable."
                return
            if r.status_code not in (200, 201):
                self.error_message = normalize_detail(r, "Registration failed")
                return
            self.success_message = "Account created. Please log in."
            yield rx.redirect("/login")
        finally:
            self.loading = False

    @rx.event
    async def logout(self):
        if self.session_id:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.delete(
                        f"{API_BASE}/sessions/{self.session_id}"
                    )
            except Exception:
                logging.exception("Unexpected error")
        self.session_id = ""
        self.access_token = ""
        self.is_authenticated = False
        self.user_id = 0
        self.username = ""
        self.email = ""
        self.business_id = ""
        self.has_secret = False
        return rx.redirect("/login")

    @rx.event
    async def update_profile(self, form_data: dict):
        self.error_message = ""
        self.success_message = ""
        self.loading = True
        try:
            payload = {
                "tin": form_data.get("tin", "").strip() or None,
                "party_name": form_data.get("party_name", "").strip() or None,
                "telephone": form_data.get("telephone", "").strip() or None,
                "street_name": form_data.get("street_name", "").strip() or None,
                "city_name": form_data.get("city_name", "").strip() or None,
                "postal_zone": form_data.get("postal_zone", "").strip() or None,
                "country": form_data.get("country", "").strip() or None,
                "state": form_data.get("state", "").strip() or None,
                "lga": form_data.get("lga", "").strip() or None,
            }
            resp = await self._api_request(
                "PATCH", "/auth/me/profile", json=payload
            )
            if resp is None:
                return
            if resp.status_code != 200:
                self.error_message = normalize_detail(resp, "Update failed")
                return
            self.success_message = "Profile updated successfully."
            yield AuthState.load_profile
        finally:
            self.loading = False

    @rx.event
    async def update_cert_key(self, form_data: dict):
        self.error_message = ""
        self.success_message = ""
        self.loading = True
        try:
            cert = form_data.get("certificate", "").strip()
            pubkey = form_data.get("public_key", "").strip()
            if not cert and not pubkey:
                self.error_message = (
                    "Provide at least one of certificate or public key."
                )
                return
            payload = {}
            if cert:
                payload["certificate"] = cert
            if pubkey:
                payload["public_key"] = pubkey
            resp = await self._api_request(
                "PATCH", "/auth/me/cert-key", json=payload
            )
            if resp is None:
                return
            if resp.status_code != 200:
                self.error_message = normalize_detail(resp, "Update failed")
                return
            self.success_message = "FIRS PKI credentials updated."
            yield AuthState.load_profile
        finally:
            self.loading = False

    @rx.event
    async def update_secret(self, form_data: dict):
        self.error_message = ""
        self.success_message = ""
        self.loading = True
        try:
            secret = form_data.get("user_secret", "")
            confirm = form_data.get("confirm_secret", "")
            if not secret:
                self.error_message = "Signing secret cannot be empty."
                return
            if secret != confirm:
                self.error_message = "Secrets do not match."
                return
            resp = await self._api_request(
                "PATCH", "/auth/me/secret", json={"user_secret": secret}
            )
            if resp is None:
                return
            if resp.status_code != 200:
                self.error_message = normalize_detail(resp, "Update failed")
                return
            self.success_message = "Signing secret updated."
            self.has_secret = True
            if self.session_id:
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        await client.patch(
                            f"{API_BASE}/sessions/{self.session_id}/secret",
                            json={"user_secret": secret},
                        )
                except Exception:
                    logging.exception("Unexpected error")
        finally:
            self.loading = False

    @rx.event
    def clear_messages(self):
        self.error_message = ""
        self.success_message = ""