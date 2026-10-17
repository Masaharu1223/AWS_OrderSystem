"""ローカル開発・単体テスト・契約テスト用のフェイク決済プロバイダ。

外部ネットワーク・SSMに一切触れない。`PAYMENT_PROVIDER=fake`のときに使われる
(docs/requirements.md §12.1.1)。
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from adapters.payment.base import PaymentNotificationError, PaymentSignatureError
from domain.payment.models import PaymentResult

_VALID_SIGNATURE = "valid"


class FakePaymentProvider:
    """単純なJSONボディ(`{"orderId": str, "outcome": str}`)をそのまま解釈する偽実装。

    `x-fake-signature`ヘッダの値で、署名検証の成功/失敗パスの両方を呼び出し側が模擬できる。
    """

    def create_payment(self, order_id: str, amount_yen: int) -> str:
        return f"https://fake-payment.local/checkout/{order_id}"

    def verify_and_parse_notification(
        self, raw_body: str, headers: Mapping[str, str]
    ) -> PaymentResult:
        if headers.get("x-fake-signature") != _VALID_SIGNATURE:
            raise PaymentSignatureError("invalid fake signature")
        try:
            payload = json.loads(raw_body)
            order_id = str(payload["orderId"])
            outcome = payload["outcome"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise PaymentNotificationError("malformed fake notification body") from exc
        if outcome not in ("succeeded", "failed"):
            raise PaymentNotificationError(f"unknown outcome: {outcome!r}")
        return PaymentResult(order_id=order_id, outcome=outcome)
