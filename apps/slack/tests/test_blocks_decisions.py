from apps.slack.blocks_decisions import decisions_state_hash


class TestDecisionsStateHash:
    def test_stable(self):
        decs = [{"id": "d-001", "status": "ai-default"}]
        h1 = decisions_state_hash(decs, {})
        h2 = decisions_state_hash(decs, {})
        assert h1 == h2

    def test_changes_with_new_decision(self):
        decs1 = [{"id": "d-001", "status": "ai-default"}]
        decs2 = [{"id": "d-001", "status": "ai-default"},
                 {"id": "d-002", "status": "ai-default"}]
        h1 = decisions_state_hash(decs1, {})
        h2 = decisions_state_hash(decs2, {})
        assert h1 != h2

    def test_changes_with_status_change(self):
        decs1 = [{"id": "d-001", "status": "ai-default"}]
        decs2 = [{"id": "d-001", "status": "overridden"}]
        h1 = decisions_state_hash(decs1, {})
        h2 = decisions_state_hash(decs2, {})
        assert h1 != h2
