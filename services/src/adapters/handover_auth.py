"""自動受渡検知システムからのAPI呼び出しを認証する。

docs/architecture.md §7.5: このプロジェクトが使っているAPI Gateway(HTTP API)には
APIキー機能自体が存在しない(REST API固有の機能)。そのためSSMパラメータストアに保管した
合言葉と`x-api-key`ヘッダの値をLambda内で自分で比較する方式にした(architect相談の結果)。
"""

from __future__ import annotations

import hmac

import boto3


class HandoverAuthenticator:
    def __init__(self, parameter_name: str) -> None:
        client = boto3.client("ssm")
        response = client.get_parameter(Name=parameter_name, WithDecryption=True)
        self._expected_key: str = response["Parameter"]["Value"]

    def verify(self, provided_key: str | None) -> bool:
        """定時間比較(タイミング攻撃対策)で合言葉を照合する。"""
        if provided_key is None:
            return False
        return hmac.compare_digest(provided_key, self._expected_key)
