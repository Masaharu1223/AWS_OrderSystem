import pytest

from adapters.payment.factory import get_payment_provider
from adapters.payment.fake_payment_client import FakePaymentProvider


def test_get_payment_provider_returns_fake_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYMENT_PROVIDER", "fake")
    provider = get_payment_provider()
    assert isinstance(provider, FakePaymentProvider)


def test_get_payment_provider_rejects_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYMENT_PROVIDER", "unknown")
    with pytest.raises(RuntimeError, match="unsupported PAYMENT_PROVIDER"):
        get_payment_provider()


def test_get_payment_provider_rejects_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAYMENT_PROVIDER", raising=False)
    with pytest.raises(RuntimeError, match="unsupported PAYMENT_PROVIDER"):
        get_payment_provider()
