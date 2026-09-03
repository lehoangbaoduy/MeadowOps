"""Password hashing for `live.user` (Unit 17a, MEADOWOPS-DOM-010).
argon2-cffi, not passlib — security design review of this unit: passlib is
unmaintained (last release 2020) and its bcrypt backend throws on newer
bcrypt versions during version probing. argon2id via library defaults, no
hand-tuned cost params for two users.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
