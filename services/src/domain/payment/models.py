"""決済結果(PaymentResult)のドメインモデル。AWS非依存。

決済プロバイダ(PayPay/Stripe/フェイク等)ごとの通知フォーマットの違いは
adapters/payment/配下で吸収し、呼び出し側には必ずこの共通の形で返す
(docs/requirements.md §12.1.1)。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

PaymentOutcome = Literal["succeeded", "failed"]


class PaymentResult(BaseModel):
    """決済プロバイダからの通知を検証・解釈した結果。"""

    model_config = ConfigDict(frozen=True)

    order_id: str
    outcome: PaymentOutcome
