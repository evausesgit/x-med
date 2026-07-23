from app.services.search_notifications import _build_message


def test_notification_includes_user_account():
    msg = _build_message(
        status="ok",
        query="Digest on-demand · Cardiologie · 30 j",
        duration_s=42.0,
        metrics={"method": "v2"},
        progress_events=(),
        user="eva@example.com",
    )
    assert "Compte: eva@example.com" in msg
    assert "Digest on-demand · Cardiologie · 30 j" in msg


def test_notification_without_user_has_no_account_line():
    msg = _build_message(
        status="ok",
        query="metformine",
        duration_s=1.0,
        metrics={},
        progress_events=(),
    )
    assert "Compte:" not in msg
