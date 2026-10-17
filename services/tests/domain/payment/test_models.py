import pytest
from pydantic import ValidationError

from domain.payment.models import PaymentResult


def test_payment_result_accepts_succeeded_outcome() -> None:
    result = PaymentResult(order_id="ord-xyz", outcome="succeeded")
    assert result.order_id == "ord-xyz"
    assert result.outcome == "succeeded"


def test_payment_result_accepts_failed_outcome() -> None:
    result = PaymentResult(order_id="ord-xyz", outcome="failed")
    assert result.outcome == "failed"


def test_payment_result_rejects_unknown_outcome() -> None:
    with pytest.raises(ValidationError):
        PaymentResult(order_id="ord-xyz", outcome="pending")  # type: ignore[arg-type]
