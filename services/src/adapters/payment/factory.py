"""使用する決済プロバイダを環境変数で選ぶ(docs/requirements.md §12.1.1)。

プロバイダの切り替えはコード変更ではなく`PAYMENT_PROVIDER`環境変数(CDK注入)で行う。
"""

from __future__ import annotations

import os

from adapters.payment.base import PaymentProvider


def get_payment_provider() -> PaymentProvider:
    provider_name = os.environ.get("PAYMENT_PROVIDER", "")
    if provider_name == "fake":
        from adapters.payment.fake_payment_client import FakePaymentProvider

        return FakePaymentProvider()
    raise RuntimeError(f"unsupported PAYMENT_PROVIDER: {provider_name!r}")
