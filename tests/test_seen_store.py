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


def test_pending_helpers_and_atomic_seen_clear():
    store = SeenStore(":memory:")

    store.mark_pending("t1_pending")
    store.mark_pending("t1_pending")
    assert store.list_pending() == ["t1_pending"]

    store.mark_seen_and_clear_pending("t1_pending")

    assert store.is_seen("t1_pending")
    assert store.list_pending() == []
    store.close()


def test_clear_pending():
    store = SeenStore(":memory:")

    store.mark_pending("t1_pending")
    store.clear_pending("t1_pending")

    assert store.list_pending() == []
    store.close()


def test_verdict_cache_hit_and_expiry():
    store = SeenStore(":memory:")

    store.store_cached_verdict("key", "llm", '{"source":"llm"}', now=1000.0)

    assert store.get_cached_verdict("key", ttl_seconds=100, now=1050.0) == '{"source":"llm"}'
    assert store.get_cached_verdict("key", ttl_seconds=100, now=1201.0) is None
    store.close()
