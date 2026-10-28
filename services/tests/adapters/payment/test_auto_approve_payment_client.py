"""AutoApprovePaymentClient専用テスト。

意図的に「未知の注文にはNone」「create_paymentはhttps URLを返す」という
test_contract.pyの前提を満たさない実装のため、共有の契約テスト(_providers())には
加えず、ここで単独に検証する(docs/requirements.md §12.1.1)。
"""

from __future__ import annotations

from adapters.payment.auto_approve_payment_client import AutoApprovePaymentClient


def test_create_payment_returns_a_string() -> None:
    provider = AutoApprovePaymentClient()
    url = provider.create_payment(order_id="ord-xyz", amount_yen=500)
    assert isinstance(url, str)


def test_get_payment_status_always_returns_succeeded() -> None:
    provider = AutoApprovePaymentClient()
    assert provider.get_payment_status("ord-xyz") == "succeeded"
    assert provider.get_payment_status("ord-never-created") == "succeeded"
