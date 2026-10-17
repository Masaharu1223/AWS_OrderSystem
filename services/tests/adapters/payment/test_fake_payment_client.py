import pytest

from adapters.payment.base import PaymentNotificationError, PaymentSignatureError
from adapters.payment.fake_payment_client import FakePaymentProvider

_VALID_HEADERS = {"x-fake-signature": "valid"}


def test_create_payment_returns_checkout_url_containing_order_id() -> None:
    provider = FakePaymentProvider()
    url = provider.create_payment(order_id="ord-xyz", amount_yen=980)
    assert url == "https://fake-payment.local/checkout/ord-xyz"


def test_verify_and_parse_notification_parses_succeeded_outcome() -> None:
    provider = FakePaymentProvider()
    result = provider.verify_and_parse_notification(
        raw_body='{"orderId": "ord-xyz", "outcome": "succeeded"}',
        headers=_VALID_HEADERS,
    )
    assert result.order_id == "ord-xyz"
    assert result.outcome == "succeeded"


def test_verify_and_parse_notification_parses_failed_outcome() -> None:
    provider = FakePaymentProvider()
    result = provider.verify_and_parse_notification(
        raw_body='{"orderId": "ord-xyz", "outcome": "failed"}',
        headers=_VALID_HEADERS,
    )
    assert result.outcome == "failed"


def test_verify_and_parse_notification_rejects_invalid_signature() -> None:
    provider = FakePaymentProvider()
    with pytest.raises(PaymentSignatureError):
        provider.verify_and_parse_notification(
            raw_body='{"orderId": "ord-xyz", "outcome": "succeeded"}',
            headers={"x-fake-signature": "invalid"},
        )


def test_verify_and_parse_notification_rejects_missing_signature_header() -> None:
    provider = FakePaymentProvider()
    with pytest.raises(PaymentSignatureError):
        provider.verify_and_parse_notification(
            raw_body='{"orderId": "ord-xyz", "outcome": "succeeded"}',
            headers={},
        )


def test_verify_and_parse_notification_rejects_malformed_body() -> None:
    provider = FakePaymentProvider()
    with pytest.raises(PaymentNotificationError):
        provider.verify_and_parse_notification(raw_body="not json", headers=_VALID_HEADERS)


def test_verify_and_parse_notification_rejects_unknown_outcome() -> None:
    provider = FakePaymentProvider()
    with pytest.raises(PaymentNotificationError):
        provider.verify_and_parse_notification(
            raw_body='{"orderId": "ord-xyz", "outcome": "pending"}',
            headers=_VALID_HEADERS,
        )
