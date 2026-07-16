from src.review.telegram_bot import apply_decision
from src.storage.database import ReelRow, session_scope


def _make_reel(status="pending_review") -> int:
    with session_scope() as session:
        reel = ReelRow(trend_id=1, status=status)
        session.add(reel)
        session.flush()
        return reel.id


def _status(reel_id) -> str:
    with session_scope() as session:
        return session.get(ReelRow, reel_id).status


def test_approve_sets_status():
    reel_id = _make_reel()
    assert apply_decision(reel_id, "approve")
    assert _status(reel_id) == "approved"


def test_reject_and_regenerate():
    a, b = _make_reel(), _make_reel()
    apply_decision(a, "reject")
    apply_decision(b, "regen")
    assert _status(a) == "rejected"
    assert _status(b) == "regenerate"


def test_double_decision_is_refused():
    reel_id = _make_reel()
    apply_decision(reel_id, "approve")
    ack = apply_decision(reel_id, "reject")
    assert "bereits" in ack
    assert _status(reel_id) == "approved"


def test_unknown_action_and_missing_reel():
    assert apply_decision(_make_reel(), "explode") is None
    assert apply_decision(99999, "approve") is None
