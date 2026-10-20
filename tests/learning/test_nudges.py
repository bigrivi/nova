from nova.learning.nudges import build_nudge_reminder, should_nudge


def test_should_nudge_every_n_turns():
    assert should_nudge(5, 5) is True
    assert should_nudge(4, 5) is False
    assert should_nudge(10, 5) is True


def test_should_nudge_disabled_interval():
    assert should_nudge(5, 0) is False
    assert should_nudge(5, -1) is False


def test_should_nudge_zero_turn():
    assert should_nudge(0, 5) is False


def test_build_nudge_reminder_contains_save_memory():
    text = build_nudge_reminder()
    assert "save_memory" in text
    assert len(text) > 0
