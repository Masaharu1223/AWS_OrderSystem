"""PaymentProvider契約テスト(docs/requirements.md §12.1.1)。

全プロバイダ実装が同じ約束を守っているかを検証する。`create_payment()`の戻り値の形は
プロバイダによらず共通に検証できるが、`verify_and_parse_notification()`は正しい署名を
作る方法がプロバイダごとに違う(ヘッダ名・アルゴリズムが異なる)ため、ここでは対象外とし
個別のテストファイル(test_fake_payment_client.py等)で検証する。

PayPayPaymentClientは実SSM値・実HTTP呼び出しが必要なため、このテストの対象外とする
(計画上のトレードオフ。将来HTTPモックを追加する余地を残す)。
"""

from __future__ import annotations

import pytest

from adapters.payment.base import PaymentProvider
from adapters.payment.fake_payment_client import FakePaymentProvider

PROVIDERS: list[PaymentProvider] = [FakePaymentProvider()]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_create_payment_returns_https_checkout_url(provider: PaymentProvider) -> None:
    url = provider.create_payment(order_id="ord-xyz", amount_yen=500)
    assert isinstance(url, str)
    assert url.startswith("https://")
