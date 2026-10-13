import bcrypt
from werkzeug.security import check_password_hash, generate_password_hash

from app.modules.accounts.models import User

_LEGACY_PREFIXES = ("$2y$", "$2a$", "$2b$")


def hash_password(plain: str) -> str:
    return generate_password_hash(plain, method="scrypt")


def _is_legacy(hashed: str) -> bool:
    return hashed.startswith(_LEGACY_PREFIXES)


def verify_password(user: User, plain: str) -> bool:
    """scrypt 해시와 Laravel에서 옮겨온 bcrypt($2y$) 해시를 모두 검증한다."""
    hashed = user.password or ""
    if _is_legacy(hashed):
        normalized = "$2b$" + hashed[4:]
        try:
            return bcrypt.checkpw(plain.encode(), normalized.encode())
        except ValueError:
            return False
    try:
        return check_password_hash(hashed, plain)
    except ValueError:
        return False


def upgrade_hash_if_needed(user: User, plain: str) -> None:
    """검증에 성공한 bcrypt 해시를 scrypt로 바꾼다. 커밋은 호출한 쪽에서 한다."""
    if _is_legacy(user.password or ""):
        user.password = hash_password(plain)
