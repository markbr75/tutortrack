"""Authorization-code + PKCE OAuth2 client shared by the real providers."""

from __future__ import annotations

import base64
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from tutortrack.core.time import now

from . import http
from .base import AccountInfo, AuthError, TokenSet


@dataclass(frozen=True)
class OAuth2Client:
    provider: str
    authorize_endpoint: str
    token_endpoint: str
    client_id: str
    client_secret: str
    revoke_endpoint: str = ""
    basic_auth: bool = False  # Zoom wants client credentials as HTTP Basic
    extra_params: dict[str, str] = field(default_factory=dict)
    account: Callable[[str], AccountInfo] | None = None  # who connected, from the token

    def authorize_url(
        self, *, state: str, redirect_uri: str, code_challenge: str, scopes: tuple[str, ...]
    ) -> str:
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            **self.extra_params,
        }
        return f"{self.authorize_endpoint}?{urllib.parse.urlencode(params)}"

    def _token(self, form: dict[str, str]) -> TokenSet:
        auth = ""
        if self.basic_auth:
            raw = f"{self.client_id}:{self.client_secret}".encode()
            auth = f"Basic {base64.b64encode(raw).decode()}"
        else:
            form = {**form, "client_id": self.client_id, "client_secret": self.client_secret}
        body = http.request(
            "POST", self.token_endpoint, form=form, auth_header=auth, provider=self.provider
        ).json()
        if "access_token" not in body:
            raise AuthError(str(body.get("error_description") or "No access token returned."))
        expires = body.get("expires_in")
        account = self.account(body["access_token"]) if self.account else AccountInfo("")
        return TokenSet(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token", ""),
            expires_at=now() + timedelta(seconds=int(expires)) if expires else None,
            scopes=tuple(str(body.get("scope", "")).replace(",", " ").split()),
            account_id=account.account_id,
            account_name=account.account_name,
        )

    def exchange(self, *, code: str, redirect_uri: str, code_verifier: str) -> TokenSet:
        return self._token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            }
        )

    def refresh(self, refresh_token: str) -> TokenSet:
        tokens = self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})
        if not tokens.refresh_token:  # Google keeps the old refresh token
            tokens = TokenSet(**{**tokens.__dict__, "refresh_token": refresh_token})
        return tokens

    def revoke(self, token: str) -> None:
        if self.revoke_endpoint and token:
            http.request(
                "POST",
                self.revoke_endpoint,
                form={"token": token},
                retries=0,
                provider=self.provider,
            )
