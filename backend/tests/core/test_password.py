"""Unit 17a (MEADOWOPS-DOM-010): password hashing for the new `live.user`
table. argon2-cffi, not passlib (security design review of this unit:
passlib is unmaintained and its bcrypt backend throws on newer bcrypt
versions during version probing) — argon2id via library defaults, no
hand-tuned cost params for two users.
"""

import pytest

from app.core.password import hash_password, verify_password


def test_hash_password_does_not_return_the_plaintext() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"


def test_hash_password_is_salted_so_the_same_input_hashes_differently() -> None:
    first = hash_password("same-password")
    second = hash_password("same-password")
    assert first != second


def test_verify_password_accepts_the_correct_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_rejects_the_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("wrong password", hashed) is False


def test_verify_password_rejects_garbage_that_is_not_a_valid_hash() -> None:
    # A malformed/foreign hash must not raise (VerifyMismatchError or
    # similar) — the login endpoint needs a plain bool to fall through to a
    # generic 401, never an unhandled exception (500).
    assert verify_password("anything", "not-a-real-argon2-hash") is False


@pytest.mark.parametrize("password", ["", "x", "a" * 200])
def test_verify_password_handles_edge_case_lengths_without_raising(password: str) -> None:
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True
    assert verify_password(password + "!", hashed) is False
