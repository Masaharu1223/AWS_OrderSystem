"""決済結果の共通の型。AWS非依存。

決済プロバイダ(PayPay/Stripe/フェイク等)ごとのステータスコードの違いは
adapters/payment/配下で吸収し、呼び出し側には必ずこの共通の型で返す
(docs/requirements.md §12.1.1)。
"""

from __future__ import annotations

from typing import Literal

PaymentOutcome = Literal["succeeded", "failed"]
