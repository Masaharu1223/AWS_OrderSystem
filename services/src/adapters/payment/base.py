"""決済プロバイダの共通インターフェース。

PayPay/Stripe/フェイク等、決済サービスごとの違いはこのインターフェースの実装側
(paypay_client.py等)に閉じ込める。domain層・handlers層はこの型としか話さない
(docs/requirements.md §12.1.1)。

PayPay公式のWeb Cashier統合フローにはWebhook通知を受信するステップが無く、
リダイレクト+ポーリング確認が推奨方式であるため(2026-10-18確認)、このインター
フェースは「確認しに行く」(get_payment_status)形にしている。Webhookの受信・
署名検証は扱わない。
"""

from __future__ import annotations

from typing import Protocol

from domain.payment.models import PaymentOutcome


class PaymentProvider(Protocol):
    def create_payment(self, order_id: str, amount_yen: int) -> str:
        """決済用のチェックアウトURL(お客様をリダイレクトする先)を発行する。"""
        ...

    def get_payment_status(self, order_id: str) -> PaymentOutcome | None:
        """決済プロバイダへ現在の決済状況を問い合わせる。

        戻り値がNoneの場合はまだ確定していない(引き続きポーリングする)ことを表す。
        """
        ...


class PaymentProviderError(Exception):
    """決済プロバイダへの呼び出しが失敗した場合に送出する(呼び出し側で500へ変換、
    またはget_payment_status()ではログのみ残し次回ポーリングへフォールバックする)。
    """
