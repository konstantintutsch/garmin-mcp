"""Garmin Connect session handling: interactive login and lazy token-based access."""

import getpass
import os
import threading
from collections.abc import Callable
from pathlib import Path

from garminconnect import Garmin
from garminconnect.client.tokens import token_file_path
from garminconnect.exceptions import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from . import config

LOGIN_HINT = "Run `garmin-mcp login` in a terminal to sign in to Garmin Connect."


class NotLoggedInError(Exception):
    """No usable Garmin session is available."""


def _new_client(
    email: str | None = None,
    password: str | None = None,
    prompt_mfa: Callable[[], str] | None = None,
) -> Garmin:
    return Garmin(email=email, password=password, is_cn=config.is_cn(), prompt_mfa=prompt_mfa)


def interactive_login() -> Garmin:
    """Prompt for credentials (and MFA), then save the session tokens to the tokenstore."""
    email = os.environ.get("GARMIN_EMAIL") or input("Garmin email: ").strip()
    password = os.environ.get("GARMIN_PASSWORD") or getpass.getpass("Garmin password: ")
    garmin = _new_client(email, password, prompt_mfa=lambda: input("MFA code: ").strip())
    garmin.login()
    garmin.client.dump(config.tokenstore())
    return garmin


def _token_file() -> Path:
    return token_file_path(config.tokenstore())


def clear_tokens() -> bool:
    """Delete saved tokens. Returns True if a token file existed."""
    path = _token_file()
    if path.exists():
        path.unlink()
        return True
    return False


class GarminSession:
    """Lazily logs in from saved tokens and shares one client across tool calls."""

    def __init__(self) -> None:
        self._client: Garmin | None = None
        self._lock = threading.Lock()

    def client(self) -> Garmin:
        with self._lock:
            if self._client is None:
                self._client = self._login()
            return self._client

    def reset(self) -> None:
        with self._lock:
            self._client = None

    def _login(self) -> Garmin:
        email = os.environ.get("GARMIN_EMAIL")
        password = os.environ.get("GARMIN_PASSWORD")
        if not (email and password) and not _token_file().exists():
            raise NotLoggedInError(
                f"No saved Garmin session in {config.tokenstore()}. {LOGIN_HINT}"
            )
        garmin = _new_client(email, password)
        try:
            garmin.login(config.tokenstore())
        except GarminConnectAuthenticationError as e:
            raise NotLoggedInError(f"Garmin login failed: {e}. {LOGIN_HINT}") from e
        except GarminConnectTooManyRequestsError as e:
            raise NotLoggedInError(f"Garmin rate-limited the login: {e}") from e
        except GarminConnectConnectionError as e:
            raise NotLoggedInError(f"Could not reach Garmin Connect: {e}") from e
        return garmin
