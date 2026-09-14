"""Unit 32 (MEADOWOPS-INFRA-005): Settings._validate_attachment_storage_backend
- the model_validator added at this unit's pre-implementation security
review (decision 1627) to fail fast at Settings() construction rather than
let a misconfigured "r2" backend silently build a broken client, or a
forgotten backend flag silently keep writing to ephemeral local disk with
no error signal."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from tests.support.auth import TEST_SESSION_SECRET

_SERVICE_TOKEN = "test-internal-service-token-value-at-least-32-bytes-long"

_R2_FIELDS: dict[str, object] = {
    "r2_account_id": "test-account-id",
    "r2_access_key_id": "test-access-key-id",
    "r2_secret_access_key": "test-secret-access-key",
    "r2_bucket_name": "test-bucket",
}


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "session_secret_key": TEST_SESSION_SECRET,
        "internal_service_token": _SERVICE_TOKEN,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestAttachmentStorageBackendValidation:
    def test_local_backend_with_no_r2_fields_is_valid(self) -> None:
        settings = _settings()
        assert settings.attachment_storage_backend == "local"

    def test_r2_backend_with_all_fields_is_valid(self) -> None:
        settings = _settings(attachment_storage_backend="r2", **_R2_FIELDS)
        assert settings.attachment_storage_backend == "r2"
        assert settings.r2_bucket_name == "test-bucket"
        assert settings.r2_access_key_id is not None
        assert settings.r2_access_key_id.get_secret_value() == "test-access-key-id"

    def test_r2_backend_missing_a_field_is_rejected(self) -> None:
        incomplete = dict(_R2_FIELDS)
        del incomplete["r2_bucket_name"]
        with pytest.raises(ValidationError, match="r2_bucket_name"):
            _settings(attachment_storage_backend="r2", **incomplete)

    def test_r2_backend_missing_all_fields_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="requires all of"):
            _settings(attachment_storage_backend="r2")

    def test_local_backend_with_r2_fields_set_is_rejected(self) -> None:
        """Guards the mirror-image misconfiguration flagged at review: an
        operator who sets the r2_* secrets but forgets to also flip
        attachment_storage_backend to "r2" would otherwise get a
        local-filesystem deploy with zero error signal."""
        with pytest.raises(ValidationError, match="r2_bucket_name"):
            _settings(attachment_storage_backend="local", **_R2_FIELDS)

    def test_error_message_never_includes_the_secret_value(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            _settings(attachment_storage_backend="r2")
        assert "test-secret-access-key" not in str(exc_info.value)


class TestClaudeClientEnabledValidation:
    """Phase 4 blocker B3: claude_client_enabled=True must never silently
    construct a client with no key - see Settings.anthropic_api_key's own
    comment on why "key present" alone can't be the live/mock switch."""

    def test_disabled_by_default(self) -> None:
        settings = _settings()
        assert settings.claude_client_enabled is False

    def test_disabled_with_a_key_present_is_valid(self) -> None:
        # The expected default local-dev/CI/test shape: a real
        # ANTHROPIC_API_KEY sitting in the environment (tests/conftest.py's
        # load_dotenv of the repo-root .env) must never itself flip the
        # switch to a live client.
        settings = _settings(anthropic_api_key="sk-ant-test-key")
        assert settings.claude_client_enabled is False

    def test_enabled_with_a_key_present_is_valid(self) -> None:
        settings = _settings(
            claude_client_enabled=True, anthropic_api_key="sk-ant-test-key"
        )
        assert settings.claude_client_enabled is True
        assert settings.anthropic_api_key is not None
        assert settings.anthropic_api_key.get_secret_value() == "sk-ant-test-key"

    def test_enabled_with_no_key_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="claude_client_enabled=True"):
            _settings(claude_client_enabled=True, anthropic_api_key=None)

    def test_enabled_with_a_blank_key_is_rejected(self) -> None:
        # Found empirically: this repo's own .env had ANTHROPIC_API_KEY=
        # present but blank - pydantic-settings reads that as SecretStr(""),
        # not None. An is-None-only check would pass this straight through
        # to a cryptic SDK TypeError at the first live call instead of
        # failing fast at Settings() construction.
        with pytest.raises(ValidationError, match="claude_client_enabled=True"):
            _settings(claude_client_enabled=True, anthropic_api_key="")

    def test_enabled_with_a_whitespace_only_key_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="claude_client_enabled=True"):
            _settings(claude_client_enabled=True, anthropic_api_key="   ")

    def test_default_timeout_seconds(self) -> None:
        settings = _settings()
        assert settings.claude_client_timeout_seconds == 60.0
