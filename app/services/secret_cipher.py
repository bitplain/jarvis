from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class SecretCipherUnavailable(RuntimeError):
    pass


class SecretCipherInvalidToken(RuntimeError):
    pass


class SecretCipher:
    def __init__(self, key: str) -> None:
        normalized = key.strip()
        if not normalized:
            raise SecretCipherUnavailable("secret_cipher_key_missing")
        try:
            self._fernet = Fernet(normalized.encode("utf-8"))
        except Exception as exc:
            raise SecretCipherUnavailable("secret_cipher_key_invalid") from exc

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode("utf-8")

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise SecretCipherInvalidToken("secret_cipher_invalid_token") from exc
