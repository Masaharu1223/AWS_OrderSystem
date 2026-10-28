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
    if provider_name == "auto-approve":
        from adapters.payment.auto_approve_payment_client import AutoApprovePaymentClient

        return AutoApprovePaymentClient()
    if provider_name == "paypay":
        from adapters.payment.paypay_client import PayPayPaymentClient
        from config import (
            get_paypay_api_key_parameter_name,
            get_paypay_api_secret_parameter_name,
            get_paypay_production_mode,
            get_paypay_redirect_url,
        )

        return PayPayPaymentClient(
            api_key_parameter_name=get_paypay_api_key_parameter_name(),
            api_secret_parameter_name=get_paypay_api_secret_parameter_name(),
            redirect_url=get_paypay_redirect_url(),
            production_mode=get_paypay_production_mode(),
        )
    raise RuntimeError(f"unsupported PAYMENT_PROVIDER: {provider_name!r}")
