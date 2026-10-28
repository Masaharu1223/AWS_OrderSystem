"""PayPay for Developers(Web Cashier)と連携するPaymentProvider実装。

公式SDK `paypayopa` を使う。HMAC署名付きリクエストの生成自体はSDKに任せ、ここでは
PayPay固有のリクエスト/レスポンス形式を共通インターフェースの形に変換することだけを
担う(docs/requirements.md §12.1.1)。

PayPay公式のWeb Cashier統合フローはWebhookではなくリダイレクト+ポーリング確認を
前提としているため(2026-10-18確認、docs/requirements.md §12.1)、Webhookの受信・
署名検証はここでは扱わない。get_payment_status()が決済情報取得API
(GET /v2/codes/payments/{merchantPaymentId})を呼んで能動的に確認する。
"""

from __future__ import annotations

import sys
import types
from typing import Any

import boto3

try:
    import pkg_resources  # noqa: F401
except ModuleNotFoundError:
    # paypayopaはバージョン文字列取得(未使用のget_version()内)のためだけにpkg_resourcesを
    # importしている。これに対応する唯一の方法である古いsetuptools(<81。81以降で
    # pkg_resources自体が削除された)を依存に加えると、そちらが既知の脆弱性を持ち
    # pip-auditに引っかかる。実際に呼ぶ関数はget_version()の外では使われないため、
    # importが通りさえすればよい最小限のスタブをここで自前に用意し、脆弱なパッケージを
    # 一切インストールせずに済ませる。
    _pkg_resources_stub = types.ModuleType("pkg_resources")

    class _DistributionNotFound(Exception):
        pass

    _pkg_resources_stub.DistributionNotFound = _DistributionNotFound  # type: ignore[attr-defined]
    sys.modules["pkg_resources"] = _pkg_resources_stub

from paypayopa import Client  # noqa: E402

from adapters.payment.base import PaymentProviderError
from domain.payment.models import PaymentOutcome

_CODE_TYPE_ORDER_QR = "ORDER_QR"
_CURRENCY_JPY = "JPY"
_REDIRECT_TYPE_WEB_LINK = "WEB_LINK"
_RESULT_CODE_SUCCESS = "SUCCESS"

# PayPay側のstatus値(docs/requirements.md §12.1.1確認時点のWeb Cashier仕様書に準拠)。
_SUCCEEDED_STATUSES = frozenset({"COMPLETED"})
_FAILED_STATUSES = frozenset({"FAILED", "CANCELED", "EXPIRED", "EXPIRED_USER_CONFIRMATION"})


class PayPayPaymentClient:
    """PayPay Web Cashier(QRコード決済)のPaymentProvider実装。"""

    def __init__(
        self,
        api_key_parameter_name: str,
        api_secret_parameter_name: str,
        redirect_url: str,
        production_mode: bool,
    ) -> None:
        ssm = boto3.client("ssm")
        api_key = ssm.get_parameter(Name=api_key_parameter_name, WithDecryption=True)["Parameter"][
            "Value"
        ]
        api_secret = ssm.get_parameter(Name=api_secret_parameter_name, WithDecryption=True)[
            "Parameter"
        ]["Value"]
        self._redirect_url = redirect_url
        self._client = Client(auth=(api_key, api_secret), production_mode=production_mode)

    def create_payment(self, order_id: str, amount_yen: int) -> str:
        response = self._client.Code.create_qr_code(
            {
                "merchantPaymentId": order_id,
                "amount": {"amount": amount_yen, "currency": _CURRENCY_JPY},
                "codeType": _CODE_TYPE_ORDER_QR,
                "redirectUrl": self._redirect_url,
                "redirectType": _REDIRECT_TYPE_WEB_LINK,
            }
        )
        data = self._unwrap(response, "create_qr_code")
        url = data.get("url")
        if not url:
            raise PaymentProviderError("PayPay create_qr_code response missing data.url")
        return str(url)

    def get_payment_status(self, order_id: str) -> PaymentOutcome | None:
        response = self._client.Code.get_payment_details(order_id)
        data = self._unwrap(response, "get_payment_details")
        status = data.get("status")
        if status in _SUCCEEDED_STATUSES:
            return "succeeded"
        if status in _FAILED_STATUSES:
            return "failed"
        return None  # CREATED等、まだ未確定

    def _unwrap(self, response: dict[str, Any], api_name: str) -> dict[str, Any]:
        """paypayopaは常にレスポンスJSONを返す(HTTPエラーでも例外を送出しない)ため、
        resultInfo.codeを見て自前で成否を判定する。
        """
        result_code = response.get("resultInfo", {}).get("code")
        if result_code != _RESULT_CODE_SUCCESS:
            raise PaymentProviderError(
                f"PayPay {api_name} failed: {response.get('resultInfo')}"
            )
        data = response.get("data")
        if not isinstance(data, dict):
            raise PaymentProviderError(f"PayPay {api_name} response missing data")
        return data
