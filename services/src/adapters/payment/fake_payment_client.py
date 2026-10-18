"""ローカル開発・単体テスト・契約テスト用のフェイク決済プロバイダ。

外部ネットワーク・SSMに一切触れない。`PAYMENT_PROVIDER=fake`のときに使われる
(docs/requirements.md §12.1.1)。
"""

from __future__ import annotations

from domain.payment.models import PaymentOutcome


class FakePaymentProvider:
    """インメモリの辞書で決済結果を模擬する偽実装。

    テスト側が`set_outcome()`で先に結果を仕込んでおくことで、`get_payment_status()`
    がPayPayからの確認結果を返すのと同じ流れを再現できる。何も仕込んでいない注文は
    「まだ未確定」を表すNoneを返す。
    """

    def __init__(self) -> None:
        self._outcomes: dict[str, PaymentOutcome] = {}

    def create_payment(self, order_id: str, amount_yen: int) -> str:
        return f"https://fake-payment.local/checkout/{order_id}"

    def set_outcome(self, order_id: str, outcome: PaymentOutcome) -> None:
        """テストから、指定した注文の決済結果を事前に設定する。"""
        self._outcomes[order_id] = outcome

    def get_payment_status(self, order_id: str) -> PaymentOutcome | None:
        return self._outcomes.get(order_id)
