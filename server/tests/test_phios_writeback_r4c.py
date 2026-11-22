"""Agentora R4c: single-POST durable receipt verification and GET-only reconciliation."""
from __future__ import annotations

import json
from unittest.mock import Mock
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import settings
from app.integrations.phios_client import (
    IntegrationClientError, IntegrationDeliveryUncertain, PhiOSClient,
)
from app.integrations.schemas import AgentExecutionOutcome
from app.integrations.writeback_idempotency import PROTOCOL, canonical_envelope, operation_id
from app.models import IntegrationRun
from app.services.integration_orchestrator import IntegrationOrchestrator


def _payload():
    return {
        'session_id': 'session-1', 'task_id': 'job-123',
        'raw_payload': {'outcome': {
            'job_id': 'job-123', 'status': 'completed', 'summary': 'Done',
        }},
    }


def _envelope():
    payload = _payload()
    value = json.loads(canonical_envelope(payload, created_at_utc='2026-11-21T19:00:00Z'))
    value['operation_id'] = operation_id(payload)
    return value


def _receipt(op, state='published'):
    result = {'operation_id': op, 'state': state, 'ok': state == 'published'}
    if state == 'published':
        result.update(receipt_id='receipt-123', record_id='agentora-writeback-' + op)
    return result


def _client(monkeypatch):
    monkeypatch.setattr(settings, 'agentora_phios_writeback_v1_enabled', True)
    client = PhiOSClient()
    client.enabled = True
    client.mock_mode = False
    client.base_url = 'http://127.0.0.1:8090'
    client.api_key = 'test-credential-0123456789abcdef0123456789abcdef'
    return client


def test_versioned_post_sends_exact_persisted_envelope_once(monkeypatch):
    client = _client(monkeypatch)
    payload = _envelope()
    seen = []

    def post(url, **kwargs):
        seen.append((url, kwargs))
        return httpx.Response(
            200, request=httpx.Request('POST', url),
            json=_receipt(payload['operation_id']),
        )

    monkeypatch.setattr(httpx, 'post', post)
    assert client.write_mission_result_v1(payload)['state'] == 'published'
    assert len(seen) == 1
    assert seen[0][0] == 'http://127.0.0.1:8090/api/v1/agentora/writeback'
    assert seen[0][1]['json'] == payload
    assert seen[0][1]['headers']['X-API-Key'] == client.api_key


@pytest.mark.parametrize('status', [202, 408, 425, 500, 503])
def test_pending_or_ambiguous_response_never_retries_post(monkeypatch, status):
    client = _client(monkeypatch)
    calls = []
    envelope = _envelope()

    def post(url, **kwargs):
        calls.append(url)
        return httpx.Response(
            status, request=httpx.Request('POST', url),
            json=_receipt(envelope['operation_id'], 'pending'),
        )

    monkeypatch.setattr(httpx, 'post', post)
    with pytest.raises(IntegrationDeliveryUncertain):
        client.write_mission_result_v1(envelope)
    assert calls == ['http://127.0.0.1:8090/api/v1/agentora/writeback']


@pytest.mark.parametrize('status', [400, 401, 403, 404, 409, 415])
def test_definitive_rejection_has_no_legacy_fallback(monkeypatch, status):
    client = _client(monkeypatch)
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        return httpx.Response(status, request=httpx.Request('POST', url))

    monkeypatch.setattr(httpx, 'post', post)
    with pytest.raises(IntegrationClientError) as exc:
        client.write_mission_result_v1(_envelope())
    assert not isinstance(exc.value, IntegrationDeliveryUncertain)
    assert len(calls) == 1
    assert calls[0].endswith('/api/v1/agentora/writeback')


@pytest.mark.parametrize('response', [
    {'ok': True, 'state': 'published', 'operation_id': 'f' * 64, 'receipt_id': 'x', 'record_id': 'y'},
    {'ok': False, 'state': 'published', 'operation_id': operation_id(_payload()),
     'receipt_id': 'x', 'record_id': 'y'},
    {'ok': True, 'state': 'pending', 'operation_id': operation_id(_payload()),
     'receipt_id': 'x', 'record_id': 'y'},
    {'ok': True, 'state': 'published', 'operation_id': operation_id(_payload())},
])
def test_unverifiable_200_ack_is_held(monkeypatch, response):
    client = _client(monkeypatch)
    monkeypatch.setattr(httpx, 'post', lambda url, **kwargs: httpx.Response(
        200, request=httpx.Request('POST', url), json=response,
    ))
    with pytest.raises(IntegrationDeliveryUncertain):
        client.write_mission_result_v1(_envelope())


def test_refuses_nonloopback_disabled_or_forged_operation_without_post(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(httpx, 'post', lambda *args, **kwargs: pytest.fail('network called'))
    client.base_url = 'http://example.org:8090'
    with pytest.raises(IntegrationClientError, match='127.0.0.1'):
        client.write_mission_result_v1(_envelope())
    client.base_url = 'http://127.0.0.1:8090'
    payload = _envelope()
    payload['operation_id'] = 'a' * 64
    with pytest.raises(IntegrationClientError, match='identity'):
        client.write_mission_result_v1(payload)
    monkeypatch.setattr(settings, 'agentora_phios_writeback_v1_enabled', False)
    with pytest.raises(IntegrationClientError, match='not enabled'):
        client.write_mission_result_v1(_envelope())


@pytest.mark.parametrize('status,state', [
    (200, 'published'), (202, 'pending'), (404, 'not_found'),
])
def test_get_only_receipt_status_has_no_side_effect(monkeypatch, status, state):
    client = _client(monkeypatch)
    op = operation_id(_payload())
    requests = []

    def get(url, **kwargs):
        requests.append(url)
        return httpx.Response(
            status, request=httpx.Request('GET', url),
            json=_receipt(op, state),
        )

    monkeypatch.setattr(httpx, 'get', get)
    assert client.writeback_receipt_status_v1(op)['state'] == state
    assert requests == ['http://127.0.0.1:8090/api/v1/agentora/writeback/' + op]


class StubSession:
    def __init__(self, row):
        self.row = row
        self.committed = []
        self.envelopes = []

    def add(self, obj):
        assert obj is self.row

    def commit(self):
        self.committed.append(self.row.writeback_status)
        self.envelopes.append(self.row.writeback_request_json)

    def exec(self, statement):
        # Simulate the atomic conditional update only in the old in-memory
        # orchestrator unit tests. SQLite race tests separately exercise SQL.
        params = statement.compile().params
        target = params.get('writeback_status')
        held = self.row.writeback_status in {'dispatching', 'needs_reconciliation'}
        # The initial dispatch claim requires an eligible state; published
        # reconciliation requires the opposite. The production SQL is tested
        # separately with two real concurrent SQLite sessions.
        if target == 'dispatching' and held:
            return SimpleNamespace(rowcount=0)
        if target == 'written' and not held:
            return SimpleNamespace(rowcount=0)
        for name in ('writeback_status', 'writeback_request_json',
                     'writeback_operation_id', 'writeback_outcome_hash',
                     'last_writeback_attempt_at', 'writeback_at',
                     'last_writeback_hash', 'writeback_error'):
            if name in params:
                setattr(self.row, name, params[name])
        return SimpleNamespace(rowcount=1)

    def rollback(self):
        pass

    def refresh(self, obj):
        assert obj is self.row

    def get(self, model, ident):
        assert model is IntegrationRun and ident == self.row.id
        return self.row


def _orchestrator():
    outcome = AgentExecutionOutcome(
        job_id='job-r4c', status='completed', summary='Completed with evidence',
    )
    row = IntegrationRun(
        id=211, phios_session_id='session-211', agentception_job_id='job-r4c',
        repo='owner/repo', objective='Verify receipts', status='completed',
        summary=outcome.summary, agentception_result_json=outcome.model_dump_json(),
    )
    session = StubSession(row)
    service = IntegrationOrchestrator(session)
    service._log_event = Mock()
    service._evaluate_run = Mock()
    service._persist_snapshot = Mock()
    service._maybe_send_alert = Mock()
    service.phios.write_mission_result = Mock(
        side_effect=AssertionError('legacy POST must not run'),
    )
    service.phios.write_mission_result_v1 = Mock()
    service.phios.writeback_receipt_status_v1 = Mock()
    return service, session, row, outcome


def test_dispatch_persists_identical_envelope_before_post(monkeypatch):
    monkeypatch.setattr(settings, 'agentora_phios_writeback_v1_enabled', True)
    service, session, row, outcome = _orchestrator()

    def send(envelope):
        assert session.committed == ['dispatching']
        assert json.loads(session.envelopes[0]) == envelope
        assert envelope['operation_id'] == row.writeback_operation_id
        return _receipt(envelope['operation_id'])

    service.phios.write_mission_result_v1.side_effect = send
    response = service._perform_writeback(row, outcome, '', None)
    assert response['ok'] and row.writeback_status == 'written'
    assert session.committed == ['dispatching', 'written']
    assert row.writeback_outcome_hash
    service.phios.write_mission_result.assert_not_called()


def test_uncertain_dispatch_held_and_status_only_reconciliation(monkeypatch):
    monkeypatch.setattr(settings, 'agentora_phios_writeback_v1_enabled', True)
    service, session, row, outcome = _orchestrator()
    service.phios.write_mission_result_v1.side_effect = IntegrationDeliveryUncertain('202 pending')
    with pytest.raises(IntegrationDeliveryUncertain):
        service._perform_writeback(row, outcome, '', None)
    assert session.committed == ['dispatching', 'needs_reconciliation']
    persisted = json.loads(row.writeback_request_json)
    op = row.writeback_operation_id
    assert persisted['operation_id'] == op

    with pytest.raises(IntegrationClientError, match='reconcile before retrying'):
        service._perform_writeback(row, outcome, '', None)
    service.phios.write_mission_result_v1.assert_called_once()

    service.phios.writeback_receipt_status_v1.return_value = _receipt(op, 'pending')
    result = service.reconcile_writeback_v1(row.id)
    assert not result['ok'] and result['held']
    assert row.writeback_status == 'needs_reconciliation'
    service.phios.writeback_receipt_status_v1.return_value = _receipt(op, 'not_found')
    result = service.reconcile_writeback_v1(row.id)
    assert result['held'] and row.writeback_status == 'needs_reconciliation'
    service.phios.writeback_receipt_status_v1.return_value = _receipt(op)
    assert service.reconcile_writeback_v1(row.id)['reconciled']
    assert row.writeback_status == 'written'
    assert row.last_writeback_hash == row.writeback_outcome_hash
    service.phios.write_mission_result_v1.assert_called_once()
    assert service.phios.writeback_receipt_status_v1.call_count == 3


def test_bad_persisted_identity_never_queries_network(monkeypatch):
    monkeypatch.setattr(settings, 'agentora_phios_writeback_v1_enabled', True)
    service, _, row, _ = _orchestrator()
    row.writeback_status = 'needs_reconciliation'
    row.writeback_request_json = json.dumps(_envelope())
    row.writeback_operation_id = 'f' * 64
    with pytest.raises(IntegrationClientError, match='immutable persisted envelope'):
        service.reconcile_writeback_v1(row.id)
    service.phios.writeback_receipt_status_v1.assert_not_called()


def test_legacy_orchestration_is_unchanged_when_r4c_off(monkeypatch):
    monkeypatch.setattr(settings, 'agentora_phios_writeback_v1_enabled', False)
    service, _, row, outcome = _orchestrator()
    service.phios.write_mission_result.side_effect = None
    service.phios.write_mission_result.return_value = {'ok': True}
    assert service._perform_writeback(row, outcome, '', None)['ok']
    assert row.writeback_request_json == '{}'
    service.phios.write_mission_result_v1.assert_not_called()
