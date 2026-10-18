"""PaymentProvider契約テスト(docs/requirements.md §12.1.1)。

全プロバイダ実装が同じ約束を守っているかを検証する。

PayPayPaymentClientは実SSM値・実HTTP呼び出しが必要なため、このテストの対象外とする
(計画上のトレードオフ。将来HTTPモックを追加する余地を残す)。
"""

from __future__ import annotations

import pytest

from adapters.payment.base import PaymentProvider
from adapters.payment.fake_payment_client import FakePaymentProvider


def _providers() -> list[PaymentProvider]:
    return [FakePaymentProvider()]


@pytest.mark.parametrize("provider", _providers())
def test_create_payment_returns_https_checkout_url(provider: PaymentProvider) -> None:
    url = provider.create_payment(order_id="ord-xyz", amount_yen=500)
    assert isinstance(url, str)
    assert url.startswith("https://")


@pytest.mark.parametrize("provider", _providers())
def test_get_payment_status_returns_none_for_unknown_order(provider: PaymentProvider) -> None:
    assert provider.get_payment_status("ord-never-created") is None
