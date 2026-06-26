import jwt
import pytest
from platform_core.models import Role
from platform_core.security import (
    create_access_token,
    decode_access_token,
    generate_api_key,
    hash_password,
    role_allows,
    verify_api_key,
    verify_password,
)

pytestmark = pytest.mark.unit


def test_password_hash_roundtrip():
    h = hash_password("s3cret!")
    assert h != "s3cret!"
    assert verify_password("s3cret!", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip_carries_claims():
    token = create_access_token(subject="u1", tenant_id="t1", role=Role.EDITOR)
    claims = decode_access_token(token)
    assert claims["sub"] == "u1"
    assert claims["tid"] == "t1"
    assert claims["role"] == "editor"


def test_jwt_rejects_tampered_token():
    token = create_access_token(subject="u1", tenant_id="t1", role=Role.VIEWER)
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token + "x", "wrong-secret", algorithms=["HS256"])


def test_api_key_generation_and_verification():
    full, prefix, hashed = generate_api_key()
    assert full.startswith(prefix)
    assert verify_api_key(full, hashed)
    assert not verify_api_key("dpk_dead.beef", hashed)


@pytest.mark.parametrize(
    ("actual", "required", "expected"),
    [
        (Role.ADMIN, Role.VIEWER, True),
        (Role.EDITOR, Role.EDITOR, True),
        (Role.VIEWER, Role.EDITOR, False),
        (Role.VIEWER, Role.ADMIN, False),
    ],
)
def test_rbac_hierarchy(actual, required, expected):
    assert role_allows(actual, required) is expected
