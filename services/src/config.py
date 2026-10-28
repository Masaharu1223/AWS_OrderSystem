"""Lambda起動時の環境変数読込(fail-fast)。"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    table_name: str


def get_config() -> Config:
    table_name = os.environ.get("TABLE_NAME")
    if not table_name:
        raise RuntimeError("TABLE_NAME environment variable is required")
    return Config(table_name=table_name)


def get_handover_api_key_parameter_name() -> str:
    """受渡検知エンドポイント専用の合言葉が保管されているSSMパラメータの名前を読む。

    `get_config()`とは別関数にしているのは、この環境変数を必要とするのはstore-fnだけ
    だから(menu-fn/cart-fn/order-fn/status-fnはこの変数を持たないため、Configに混ぜると
    それらのLambdaまで起動時にRuntimeErrorで落ちてしまう)。
    """
    parameter_name = os.environ.get("HANDOVER_API_KEY_PARAMETER_NAME")
    if not parameter_name:
        raise RuntimeError("HANDOVER_API_KEY_PARAMETER_NAME environment variable is required")
    return parameter_name


def get_paypay_api_key_parameter_name() -> str:
    """PayPay APIキーが保管されているSSMパラメータの名前を読む。

    `PAYMENT_PROVIDER=paypay`のときだけ必要(order-fn/status-fnのみ)なので、
    `get_handover_api_key_parameter_name()`と同じ理由でConfigには混ぜない。
    """
    parameter_name = os.environ.get("PAYPAY_API_KEY_PARAMETER_NAME")
    if not parameter_name:
        raise RuntimeError("PAYPAY_API_KEY_PARAMETER_NAME environment variable is required")
    return parameter_name


def get_paypay_api_secret_parameter_name() -> str:
    """PayPay APIキーシークレットが保管されているSSMパラメータの名前を読む。"""
    parameter_name = os.environ.get("PAYPAY_API_SECRET_PARAMETER_NAME")
    if not parameter_name:
        raise RuntimeError("PAYPAY_API_SECRET_PARAMETER_NAME environment variable is required")
    return parameter_name


def get_paypay_redirect_url() -> str:
    """決済完了後にPayPayがユーザーを戻すリダイレクト先URL(web側)を読む。"""
    redirect_url = os.environ.get("PAYPAY_REDIRECT_URL")
    if not redirect_url:
        raise RuntimeError("PAYPAY_REDIRECT_URL environment variable is required")
    return redirect_url


def get_paypay_production_mode() -> bool:
    """PayPayの本番環境を使うかどうか(false ならサンドボックス)。"""
    return os.environ.get("PAYPAY_PRODUCTION_MODE", "false").lower() == "true"
