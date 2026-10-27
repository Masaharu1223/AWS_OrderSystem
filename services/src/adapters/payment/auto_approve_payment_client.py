"""PayPay加盟店申込み完了までの暫定実装(docs/requirements.md §12.1.1)。

外部通信を一切行わず、作成した決済を常に即時成功扱いにする。`order-fn`/`status-fn`の
コードパスはPayPay/フェイク実装と完全に同じものを通る(新しい分岐を増やさない)。

実際にお金のやり取りが発生しない設定のため、本番(prod)環境での使用はCDK側
(infra/lib/app-stack.ts)でsynth時にエラーとしてブロックする。
"""

from __future__ import annotations

from domain.payment.models import PaymentOutcome

_DUMMY_CHECKOUT_URL = "about:blank"


class AutoApprovePaymentClient:
    """常に即時成功を返す決済プロバイダ。PayPay加盟店申込み完了までの暫定運用用。"""

    def create_payment(self, order_id: str, amount_yen: int) -> str:
        return _DUMMY_CHECKOUT_URL

    def get_payment_status(self, order_id: str) -> PaymentOutcome | None:
        return "succeeded"
