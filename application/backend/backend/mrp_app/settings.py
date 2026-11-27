"""Write-only settings with encrypted-at-rest credentials.

Production obtains the encryption key from a read-only container secret, never
from the database/data volume.  A local development key is created with 0400
permissions only when no secret path has been configured.
"""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken

from .catalog import RUNTIMES

TOKEN_MODES = ("saved", "own", "none")
TARGET_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")


def valid_token(token):
    return isinstance(token, str) and 1 <= len(token) <= 4096 and not any(c in token for c in "\r\n\x00 ")


def check_target_url(runtime, url):
    """A remote policy server is reached as scheme://host:port; the scheme follows the runtime."""
    spec = RUNTIMES.get(runtime)
    if spec is None:
        raise ValueError("Unknown runtime.")
    parts = urlsplit(url) if isinstance(url, str) and len(url) <= 300 else None
    try:
        port = parts.port if parts else None
    except ValueError:
        port = None
    if (
        parts is None
        or parts.scheme not in spec["schemes"]
        or not parts.hostname
        or port is None
        or parts.path not in ("", "/")
        or parts.username
        or parts.query
        or parts.fragment
    ):
        raise ValueError(
            f"URL must look like {spec['schemes'][0]}://host:{spec['default_port']} for this container."
        )
    return f"{parts.scheme}://{parts.hostname}:{port}"


class Settings:
    def __init__(self, directory):
        self.path = Path(directory) / "settings.json"
        self.key_path = Path(os.environ.get("MRP_SETTINGS_KEY_FILE", self.path.with_name("settings.key")))
        self._fernet = None

    def _cipher(self):
        if self._fernet:
            return self._fernet
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            key = self.key_path.read_bytes().strip()
        except FileNotFoundError:
            if os.environ.get("MRP_SETTINGS_KEY_FILE"):
                raise ValueError("Configured MRP settings secret is unavailable.")
            key = Fernet.generate_key()
            fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
            with os.fdopen(fd, "wb") as handle:
                handle.write(key)
        try:
            self._fernet = Fernet(key)
        except (ValueError, TypeError) as exc:
            raise ValueError("MRP settings secret is invalid.") from exc
        return self._fernet

    def _load(self):
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def public(self):
        data = self._load()
        return {
            "hf_token_set": bool(data.get("hf_token_enc") or data.get("hf_token")),
            "hf_namespace": data.get("hf_namespace", ""),
            "targets": [
                {k: t[k] for k in ("id", "name", "runtime", "url", "token_mode")}
                | {"token_set": bool(t.get("token_enc"))}
                for t in data.get("targets", [])
            ],
        }

    def target(self, ident):
        for item in self._load().get("targets", []):
            if item["id"] == ident:
                return item
        return None

    def target_token(self, ident):
        """Token a remote target should use: its own, the saved Hub token, or none."""
        item = self.target(ident)
        if item is None:
            raise ValueError("Unknown remote target.")
        if item["token_mode"] == "own" and item.get("token_enc"):
            try:
                return self._cipher().decrypt(item["token_enc"].encode()).decode()
            except (InvalidToken, UnicodeError):
                return None
        return self.token() if item["token_mode"] == "saved" else None

    def _upsert_target(self, data, body):
        ident = body.get("id")
        if not isinstance(ident, str) or not TARGET_ID.fullmatch(ident):
            raise ValueError("Target id must be lowercase letters, digits or dashes.")
        name = body.get("name") or ident
        if not isinstance(name, str) or len(name) > 60 or any(ord(c) < 32 for c in name):
            raise ValueError("Target name must be at most 60 printable characters.")
        mode = body.get("token_mode", "saved")
        if mode not in TOKEN_MODES:
            raise ValueError("Token mode must be saved, own or none.")
        runtime = body.get("runtime")
        url = check_target_url(runtime, body.get("url"))
        targets = [t for t in data.get("targets", []) if t["id"] != ident]
        previous = next((t for t in data.get("targets", []) if t["id"] == ident), {})
        item = {"id": ident, "name": name, "runtime": runtime, "url": url, "token_mode": mode}
        token = body.get("token")
        if mode == "own":
            if token is not None:
                if not valid_token(token):
                    raise ValueError("Token must be 1–4096 characters without spaces or line breaks.")
                item["token_enc"] = self._cipher().encrypt(token.encode()).decode()
            elif previous.get("token_enc"):
                item["token_enc"] = previous["token_enc"]
            else:
                raise ValueError("Enter the token this target should use.")
        if len(targets) >= 20:
            raise ValueError("At most 20 remote targets.")
        data["targets"] = [*targets, item]

    def token(self):
        data = self._load()
        encrypted = data.get("hf_token_enc")
        if encrypted:
            try:
                return self._cipher().decrypt(encrypted.encode()).decode()
            except (InvalidToken, UnicodeError):
                return None
        # One-time compatibility path. The next settings update rewrites it encrypted.
        return data.get("hf_token") or None

    def _save(self, data):
        token = data.pop("hf_token", None)
        if token:
            data["hf_token_enc"] = self._cipher().encrypt(token.encode()).decode()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle)
        temporary.replace(self.path)

    def update(self, body):
        if set(body) - {"hf_token", "hf_namespace", "clear_hf_token", "target_upsert", "target_delete"}:
            raise ValueError("Unknown settings fields.")
        data = self._load()
        if body.get("clear_hf_token") is True:
            data.pop("hf_token", None)
            data.pop("hf_token_enc", None)
        token = body.get("hf_token")
        if token is not None:
            if (
                not isinstance(token, str)
                or not 1 <= len(token) <= 4096
                or any(c in token for c in "\r\n\x00 ")
            ):
                raise ValueError("Token must be 1–4096 characters without spaces or line breaks.")
            data["hf_token"] = token
        namespace = body.get("hf_namespace")
        if namespace is not None:
            if not isinstance(namespace, str) or (
                namespace and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", namespace)
            ):
                raise ValueError("Namespace must be a Hugging Face user or organisation name.")
            data["hf_namespace"] = namespace
        if body.get("target_upsert") is not None:
            self._upsert_target(data, body["target_upsert"])
        if body.get("target_delete") is not None:
            data["targets"] = [t for t in data.get("targets", []) if t["id"] != body["target_delete"]]
        self._save(data)
        return self.public()
