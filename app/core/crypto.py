from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


class EncryptionUnavailable(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = current_app.config.get("ENCRYPTION_KEY")
    if not key:
        raise EncryptionUnavailable("ENCRYPTION_KEY가 설정되지 않았습니다.")
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise EncryptionUnavailable("ENCRYPTION_KEY 형식이 올바르지 않습니다.") from exc


def encryption_ready() -> bool:
    try:
        _fernet()
    except EncryptionUnavailable:
        return False
    return True


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise EncryptionUnavailable("저장된 값을 복호화할 수 없습니다. 마스터키를 확인하세요.") from exc
