import os

import pytest


@pytest.fixture(autouse=True)
def _aws_test_credentials() -> None:
    """motoが実AWSに触れないよう、ダミーの認証情報・リージョンを保証する。"""
    os.environ.setdefault("AWS_DEFAULT_REGION", "ap-northeast-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
    os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
