"""R3: uncertain PhiOS writes must not be resent by any Agentora caller."""
from unittest.mock import Mock

import httpx
import pytest

from app.core.config import settings
from app.integrations.mappers import outcome_fingerprint
from app.integrations.phios_client import IntegrationClientError, IntegrationDeliveryUncertain, PhiOSClient
from app.integrations.schemas import AgentExecutionOutcome
from app.models import IntegrationRun
from app.services.integration_orchestrator import IntegrationOrchestrator


def _outcome(summary='Completed with evidence'):
    return AgentExecutionOutcome(job_id='job-r3', status='completed', summary=summary)


class StubSession:
    def __init__(self, row):
        self.row = row
        self.committed_states = []

    def add(self, obj):
        assert obj is self.row

    def commit(self):
        self.committed_states.append(self.row.writeback_status)

    def get(self, model, ident):
        assert model is IntegrationRun
        assert ident == self.row.id
        return self.row


def _orchestrator():
    outcome = _outcome()
    row = IntegrationRun(
        id=123, phios_session_id='test-session', agentception_job_id='job-r3',
        repo='owner/repo', objective='Validate reliability', status='completed',
        summary=outcome.summary, agentception_result_json=outcome.model_dump_json(),
        writeback_policy='auto', auto_writeback_enabled=True,
    )
    session = StubSession(row)
    orchestrator = IntegrationOrchestrator(session)
    orchestrator.phios.write_mission_result = Mock(return_value={'ok': True})
    orchestrator._log_event = Mock()
    orchestrator._evaluate_run = Mock()
    orchestrator._persist_snapshot = Mock()
    orchestrator._maybe_send_alert = Mock()
    orchestrator.evaluate_persona_policy = Mock(return_value={'ok': True})
    return orchestrator, session, row, outcome


@pytest.mark.parametrize('status', [408, 425, 500, 503])
def test_ambiguous_http_status_is_typed_without_fallback(monkeypatch, status):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        return httpx.Response(status, request=httpx.Request('POST', url), json={'error': 'problem'})

    monkeypatch.setattr(httpx, 'post', post)
    client = PhiOSClient()
    client.base_url = 'http://127.0.0.1:8090'
    with pytest.raises(IntegrationDeliveryUncertain, match=f'HTTP {status}'):
        client._post_first_success(['/mission/writeback', '/memory/write'], {'task_id': 'one'})
    assert len(calls) == 1


@pytest.mark.parametrize('kind', [httpx.TimeoutException, httpx.ConnectError])
def test_transport_uncertainty_is_typed(monkeypatch, kind):
    def post(url, **kwargs):
        raise kind('no acknowledgement', request=httpx.Request('POST', url))

    monkeypatch.setattr(httpx, 'post', post)
    with pytest.raises(IntegrationDeliveryUncertain, match='transport error'):
        PhiOSClient()._post_first_success(['/memory/write'], {'task_id': 'one'})


@pytest.mark.parametrize('payload', [b'invalid JSON', b'[]'])
def test_success_without_object_acknowledgement_is_uncertain(monkeypatch, payload):
    def post(url, **kwargs):
        return httpx.Response(200, request=httpx.Request('POST', url), content=payload)

    monkeypatch.setattr(httpx, 'post', post)
    with pytest.raises(IntegrationDeliveryUncertain):
        PhiOSClient()._post_first_success(['/memory/write'], {'task_id': 'one'})


def test_known_client_rejection_remains_definitive(monkeypatch):
    def post(url, **kwargs):
        return httpx.Response(422, request=httpx.Request('POST', url))

    monkeypatch.setattr(httpx, 'post', post)
    with pytest.raises(IntegrationClientError) as found:
        PhiOSClient()._post_first_success(['/memory/write'], {'task_id': 'one'})
    assert not isinstance(found.value, IntegrationDeliveryUncertain)


def test_success_persists_dispatch_first_then_acknowledgement():
    orchestrator, session, row, outcome = _orchestrator()
    def send(payload):
        assert session.committed_states == ['dispatching']
        return {'ok': True, 'writeback_id': 'remote-1'}

    orchestrator.phios.write_mission_result.side_effect = send
    response = orchestrator._perform_writeback(row, outcome, '', None)
    assert response['result']['writeback_id'] == 'remote-1'
    assert session.committed_states == ['dispatching', 'written']
    assert row.last_writeback_hash == outcome_fingerprint(outcome)


def test_timeout_held_for_reconciliation_blocks_manual_and_watcher(monkeypatch):
    orchestrator, session, row, outcome = _orchestrator()
    orchestrator.phios.write_mission_result.side_effect = IntegrationDeliveryUncertain('timeout')
    with pytest.raises(IntegrationDeliveryUncertain):
        orchestrator._perform_writeback(row, outcome, '', None)
    assert session.committed_states == ['dispatching', 'needs_reconciliation']
    assert row.writeback_status == 'needs_reconciliation'
    assert 'timeout' in row.writeback_error
    assert orchestrator.phios.write_mission_result.call_count == 1

    with pytest.raises(IntegrationClientError, match='reconcile before retrying'):
        orchestrator.writeback_run(row.id)
    monkeypatch.setattr(settings, 'agentora_missions_auto_writeback', True)
    orchestrator._maybe_auto_writeback(row, outcome, outcome_fingerprint(outcome))
    assert orchestrator.phios.write_mission_result.call_count == 1


@pytest.mark.parametrize('pending_status', ['dispatching', 'needs_reconciliation'])
def test_persisted_pending_status_blocks_new_attempt(pending_status):
    orchestrator, session, row, outcome = _orchestrator()
    row.writeback_status = pending_status
    with pytest.raises(IntegrationClientError, match='reconcile before retrying'):
        orchestrator._perform_writeback(row, outcome, '', None)
    assert session.committed_states == []
    orchestrator.phios.write_mission_result.assert_not_called()


def test_abnormal_exit_leaves_dispatching_state():
    orchestrator, session, row, outcome = _orchestrator()
    orchestrator.phios.write_mission_result.side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        orchestrator._perform_writeback(row, outcome, '', None)
    assert session.committed_states == ['dispatching']
    assert row.writeback_status == 'dispatching'


def test_known_rejection_can_be_corrected_and_retried():
    orchestrator, session, row, outcome = _orchestrator()
    orchestrator.phios.write_mission_result.side_effect = IntegrationClientError('HTTP 422')
    with pytest.raises(IntegrationClientError, match='422'):
        orchestrator._perform_writeback(row, outcome, '', None)
    assert row.writeback_status == 'failed'
    orchestrator.phios.write_mission_result.side_effect = None
    assert orchestrator._perform_writeback(row, outcome, '', None)['ok']
    assert row.writeback_status == 'written'
    assert orchestrator.phios.write_mission_result.call_count == 2


def test_manual_successful_duplicate_is_noop():
    orchestrator, session, row, outcome = _orchestrator()
    row.writeback_status = 'written'
    row.last_writeback_hash = outcome_fingerprint(outcome)
    response = orchestrator.writeback_run(row.id, operator_notes='second click')
    assert response['ok'] and response['skipped'] and response['reason'] == 'already-written'
    assert session.committed_states == []
    orchestrator.phios.write_mission_result.assert_not_called()


def test_changed_outcome_after_prior_success_is_new_writeback():
    orchestrator, session, row, outcome = _orchestrator()
    row.writeback_status = 'written'
    row.last_writeback_hash = outcome_fingerprint(_outcome('Old outcome'))
    assert orchestrator._perform_writeback(row, outcome, '', None)['ok']
    orchestrator.phios.write_mission_result.assert_called_once()
    assert row.last_writeback_hash == outcome_fingerprint(outcome)
