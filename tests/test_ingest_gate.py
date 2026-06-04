"""Tests for SessionGate — INV-KK-SESSION-SEPARATION enforcement."""

import pytest

from know_kernel.ingest.gate import SessionGate, SessionViolationError


class TestSessionGate:
    def test_session_gate_extraction_mode(self):
        gate = SessionGate()
        gate.record_class_a_access()
        gate.record_class_a_access()
        assert gate.is_extraction_mode
        assert not gate.is_proposal_mode

    def test_session_gate_proposal_mode(self):
        gate = SessionGate()
        gate.record_proposal()
        assert gate.is_proposal_mode
        with pytest.raises(SessionViolationError):
            gate.record_class_a_access()

    def test_session_gate_mixed_mode_rejected(self):
        gate = SessionGate()
        gate.record_class_a_access()
        with pytest.raises(SessionViolationError):
            gate.record_proposal()

    def test_session_gate_clean_session(self):
        gate = SessionGate()
        assert gate.is_clean
        assert not gate.is_extraction_mode
        assert not gate.is_proposal_mode
        gate2 = SessionGate()
        gate2.record_class_a_access()
        assert not gate2.is_clean
        gate3 = SessionGate()
        gate3.record_proposal()
        assert not gate3.is_clean
