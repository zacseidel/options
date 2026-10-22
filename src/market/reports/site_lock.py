"""Site lock: every exported data file is gzip-compressed and AES-256-GCM encrypted with one key per export.

The key comes from the pass phrase in SITE_PASSWORD (.env; NEWSFEED_PASSWORD is accepted too) via
PBKDF2-SHA256 with a fresh random salt. `lock.json` (public) carries the salt, the iteration count and an
encrypted check value, so the browser can derive the key once from the typed phrase, confirm it, and
decrypt each file as pages load (WebCrypto + DecompressionStream). The site's code stays public; its data
is unreadable without the phrase. Without a pass phrase nothing is encrypted.

Encrypted file: {"v": 1, "iv": <base64 12 bytes>, "ct": <base64 ciphertext + tag of gzip(json)>}.
"""

from __future__ import annotations

import base64
import gzip
import json
import os

from market.config import secret

PBKDF2_ITERATIONS = 250_000
CHECK = b"market-lab"


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


class Lock:
    def __init__(self, password: str, salt: bytes | None = None, iterations: int = PBKDF2_ITERATIONS):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

        self.salt, self.iterations = salt or os.urandom(16), iterations
        key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=self.salt, iterations=iterations).derive(password.encode())
        self._aead = AESGCM(key)

    def seal_bytes(self, data: bytes) -> dict:
        iv = os.urandom(12)
        return {"v": 1, "iv": _b64(iv), "ct": _b64(self._aead.encrypt(iv, data, None))}

    def seal_text(self, text: str) -> str:
        """JSON text → the encrypted wrapper's JSON text (gzip first: JSON shrinks ~5–10×)."""
        return json.dumps(self.seal_bytes(gzip.compress(text.encode(), compresslevel=6)), separators=(",", ":"))

    def open_text(self, wrapper: str) -> str:
        w = json.loads(wrapper)
        return gzip.decompress(self._aead.decrypt(base64.b64decode(w["iv"]), base64.b64decode(w["ct"]), None)).decode()

    def manifest(self) -> dict:
        check = self.seal_bytes(CHECK)
        return {"v": 1, "kdf": "PBKDF2-SHA256", "iterations": self.iterations, "salt": _b64(self.salt),
                "check": {"iv": check["iv"], "ct": check["ct"]}}


def from_env() -> Lock | None:
    password = secret("SITE_PASSWORD", "NEWSFEED_PASSWORD", required=False)
    return Lock(password) if password else None
