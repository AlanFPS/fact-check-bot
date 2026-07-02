from factcheckbot.seen_store import SeenStore


def test_seen_store_marks_and_persists(tmp_path):
    path = tmp_path / "seen.sqlite3"
    store = SeenStore(str(path))

    assert not store.is_seen("t1_a")
    store.mark_seen("t1_a")
    store.mark_seen("t1_a")
    assert store.is_seen("t1_a")
    store.close()

    reopened = SeenStore(str(path))
    assert reopened.is_seen("t1_a")
    reopened.close()
