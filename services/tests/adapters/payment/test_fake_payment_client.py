from adapters.payment.fake_payment_client import FakePaymentProvider


def test_create_payment_returns_checkout_url_containing_order_id() -> None:
    provider = FakePaymentProvider()
    url = provider.create_payment(order_id="ord-xyz", amount_yen=980)
    assert url == "https://fake-payment.local/checkout/ord-xyz"


def test_get_payment_status_returns_none_when_not_set() -> None:
    provider = FakePaymentProvider()
    assert provider.get_payment_status("ord-xyz") is None


def test_get_payment_status_returns_succeeded_after_set_outcome() -> None:
    provider = FakePaymentProvider()
    provider.set_outcome("ord-xyz", "succeeded")
    assert provider.get_payment_status("ord-xyz") == "succeeded"


def test_get_payment_status_returns_failed_after_set_outcome() -> None:
    provider = FakePaymentProvider()
    provider.set_outcome("ord-xyz", "failed")
    assert provider.get_payment_status("ord-xyz") == "failed"


def test_get_payment_status_is_scoped_per_order_id() -> None:
    provider = FakePaymentProvider()
    provider.set_outcome("ord-1", "succeeded")
    assert provider.get_payment_status("ord-2") is None
