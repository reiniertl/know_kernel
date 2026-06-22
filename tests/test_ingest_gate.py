"""Tests for SessionGate — INV-KK-SESSION-SEPARATION enforcement."""

from ingest.gate import SessionGate


class TestSessionGate:
    def test_session_gate_extraction_mode(self):
        gate = SessionGate()
        gate.record_class_a_access()
        gate.record_class_a_access()
        assert gate.is_extraction_mode

    def test_session_gate_clean_session(self):
        gate = SessionGate()
        assert gate.is_clean
        assert not gate.is_extraction_mode
        gate2 = SessionGate()
        gate2.record_class_a_access()
        assert not gate2.is_clean
