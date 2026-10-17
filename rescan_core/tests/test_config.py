"""Защита от запуска с демонстрационными секретами."""
import pytest
from pydantic import ValidationError

from app.config import Settings


def secure_settings():
    return {
        "environment": "production",
        "mis_hmac_secret": "test-hmac-" + "a" * 32,
        "pilot_salt": "test-pilot-" + "b" * 32,
        "contact_encryption_key": "test-key-" + "c" * 32,
        "contact_hash_salt": "test-hash-" + "d" * 32,
        "staff_tokens": {},
        "mis_clinic_id": "test-clinic",
    }


def test_production_rejects_defaults():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production")


@pytest.mark.parametrize("field", [
    "mis_hmac_secret", "pilot_salt", "contact_encryption_key", "contact_hash_salt",
    "staff_tokens", "mis_clinic_id",
])
def test_each_missing_production_setting_is_rejected(field):
    values = secure_settings()
    del values[field]
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_production_with_explicit_secrets_and_no_staff_tokens():
    assert Settings(_env_file=None, **secure_settings()).environment == "production"


def test_configuration_errors_do_not_print_other_secrets():
    values = secure_settings()
    values["contact_hash_salt"] = "short"
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **values)
    assert values["mis_hmac_secret"] not in str(error.value)


@pytest.mark.parametrize("environment", ["staging", "prod", "Production"])
def test_only_explicit_local_and_test_allow_defaults(environment):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment=environment)
