import boto3
from moto import mock_aws

from adapters.handover_auth import HandoverAuthenticator

_PARAMETER_NAME = "/mobile-order/dev/handover-api-key"


def _put_parameter(value: str) -> None:
    client = boto3.client("ssm")
    client.put_parameter(Name=_PARAMETER_NAME, Value=value, Type="SecureString")


@mock_aws
def test_verify_accepts_the_correct_key() -> None:
    _put_parameter("correct-secret")
    authenticator = HandoverAuthenticator(_PARAMETER_NAME)

    assert authenticator.verify("correct-secret") is True


@mock_aws
def test_verify_rejects_a_wrong_key() -> None:
    _put_parameter("correct-secret")
    authenticator = HandoverAuthenticator(_PARAMETER_NAME)

    assert authenticator.verify("wrong-secret") is False


@mock_aws
def test_verify_rejects_missing_key() -> None:
    _put_parameter("correct-secret")
    authenticator = HandoverAuthenticator(_PARAMETER_NAME)

    assert authenticator.verify(None) is False
