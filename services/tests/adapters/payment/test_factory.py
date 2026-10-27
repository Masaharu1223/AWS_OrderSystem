import boto3
import pytest
from moto import mock_aws

from adapters.payment.auto_approve_payment_client import AutoApprovePaymentClient
from adapters.payment.factory import get_payment_provider
from adapters.payment.fake_payment_client import FakePaymentProvider
from adapters.payment.paypay_client import PayPayPaymentClient


def test_get_payment_provider_returns_fake_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYMENT_PROVIDER", "fake")
    provider = get_payment_provider()
    assert isinstance(provider, FakePaymentProvider)


def test_get_payment_provider_returns_auto_approve_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAYMENT_PROVIDER", "auto-approve")
    provider = get_payment_provider()
    assert isinstance(provider, AutoApprovePaymentClient)


@mock_aws
def test_get_payment_provider_returns_paypay_client_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ssm = boto3.client("ssm")
    ssm.put_parameter(Name="/test/paypay/api-key", Value="test-key", Type="SecureString")
    ssm.put_parameter(Name="/test/paypay/api-secret", Value="test-secret", Type="SecureString")
    monkeypatch.setenv("PAYMENT_PROVIDER", "paypay")
    monkeypatch.setenv("PAYPAY_API_KEY_PARAMETER_NAME", "/test/paypay/api-key")
    monkeypatch.setenv("PAYPAY_API_SECRET_PARAMETER_NAME", "/test/paypay/api-secret")
    monkeypatch.setenv("PAYPAY_REDIRECT_URL", "https://example.com/payment/result")

    provider = get_payment_provider()

    assert isinstance(provider, PayPayPaymentClient)


def test_get_payment_provider_rejects_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYMENT_PROVIDER", "unknown")
    with pytest.raises(RuntimeError, match="unsupported PAYMENT_PROVIDER"):
        get_payment_provider()


def test_get_payment_provider_rejects_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAYMENT_PROVIDER", raising=False)
    with pytest.raises(RuntimeError, match="unsupported PAYMENT_PROVIDER"):
        get_payment_provider()
