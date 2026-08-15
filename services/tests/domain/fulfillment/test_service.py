import pytest

from domain.fulfillment.models import LineStatus, OrderStatus
from domain.fulfillment.service import derive_order_status, is_allowed_line_status_transition


@pytest.mark.parametrize(
    ("line_statuses", "expected"),
    [
        # --- docs/requirements.md §6.2 真理値表 5パターン ---
        (["WAITING"], "STORE_ACCEPTED"),
        (["WAITING", "WAITING"], "STORE_ACCEPTED"),
        (["CANCELLED"], "CANCELLED"),
        (["CANCELLED", "CANCELLED"], "CANCELLED"),
        (["PREPARING"], "PREPARING"),
        (["PREPARING", "WAITING"], "PREPARING"),
        (["READY", "PREPARING"], "PREPARING"),  # 1明細以上READY/PREPARINGだが全READYではない
        (["READY"], "READY_PICKUP"),
        (["READY", "READY"], "READY_PICKUP"),
        (["READY", "CANCELLED"], "READY_PICKUP"),  # CANCELLEDを除いて全READY
        (["HANDED_OVER"], "HANDED_OVER"),
        (["HANDED_OVER", "HANDED_OVER"], "HANDED_OVER"),
        (["HANDED_OVER", "CANCELLED"], "HANDED_OVER"),  # CANCELLEDを除いて全HANDED_OVER
        # --- §6.4 具体例(ラテL Zone A + 紅茶M Zone D)の時系列そのまま ---
        (["WAITING", "WAITING"], "STORE_ACCEPTED"),  # 12:00
        (["PREPARING", "WAITING"], "PREPARING"),  # 12:02
        (["READY", "PREPARING"], "PREPARING"),  # 12:04(ラテ完成、紅茶待ち)
        (["READY", "READY"], "READY_PICKUP"),  # 12:07
        (["HANDED_OVER", "HANDED_OVER"], "HANDED_OVER"),  # 12:09
        # --- 表に明記の無い組み合わせ: PREPARINGへフォールバック(ユーザー確認済み方針) ---
        # §14.11により、明細は個別にREADYになった時点で提供台に置かれ、お客様が持ち去ると
        # READY_PICKUP(全明細READY)を待たずにその明細だけ先にHANDED_OVERになりうる。
        (["HANDED_OVER", "WAITING"], "PREPARING"),
        (["HANDED_OVER", "PREPARING"], "PREPARING"),
        (["HANDED_OVER", "READY"], "PREPARING"),
    ],
)
def test_derive_order_status(line_statuses: list[LineStatus], expected: OrderStatus) -> None:
    assert derive_order_status(line_statuses) == expected


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [("WAITING", "PREPARING"), ("PREPARING", "READY")],
)
def test_is_allowed_line_status_transition_accepts_the_two_forward_steps(
    from_status: LineStatus, to_status: LineStatus
) -> None:
    assert is_allowed_line_status_transition(from_status, to_status) is True


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        ("WAITING", "READY"),  # 飛び越し
        ("READY", "PREPARING"),  # 逆行
        ("WAITING", "HANDED_OVER"),  # HANDED_OVERは受渡検知エンドポイント専用
        ("READY", "HANDED_OVER"),  # 同上(こちらは許可されるように見えて実際は別エンドポイント)
        ("WAITING", "CANCELLED"),  # CANCELLEDはキャンセルAPI専用
        ("PREPARING", "PREPARING"),  # 同一状態への遷移も許可しない
    ],
)
def test_is_allowed_line_status_transition_rejects_everything_else(
    from_status: LineStatus, to_status: LineStatus
) -> None:
    assert is_allowed_line_status_transition(from_status, to_status) is False
