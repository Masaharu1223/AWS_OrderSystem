"""決済プロバイダの共通インターフェース。

PayPay/Stripe/フェイク等、決済サービスごとの違いはこのインターフェースの実装側
(paypay_client.py等)に閉じ込める。domain層・handlers層はこの型としか話さない
(docs/requirements.md §12.1.1)。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from domain.payment.models import PaymentResult


class PaymentProvider(Protocol):
    def create_payment(self, order_id: str, amount_yen: int) -> str:
        """決済用のチェックアウトURL(お客様をリダイレクトする先)を発行する。"""
        ...

    def verify_and_parse_notification(
        self, raw_body: str, headers: Mapping[str, str]
    ) -> PaymentResult:
        """Webhook通知を検証し、共通の形(PaymentResult)に変換して返す。"""
        ...


class PaymentSignatureError(Exception):
    """Webhook通知の署名検証に失敗した場合に送出する(呼び出し側で401へ変換)。"""


class PaymentNotificationError(Exception):
    """未知のnotification_type等、処理対象外の通知を受けた場合に送出する。

    呼び出し側はプロバイダ側の再送ループを避けるため200で握りつぶす。
    """


class PaymentProviderError(Exception):
    """create_payment()の呼び出し自体が失敗した場合に送出する(呼び出し側で500へ変換)。"""
