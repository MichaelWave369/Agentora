from datetime import datetime, timezone
from urllib.parse import urlsplit

from app.integrations.writeback_idempotency import PROTOCOL, canonical_envelope, operation_id

import httpx

from app.core.config import settings
from app.integrations.schemas import (
    ArchitecturalPrinciple,
    CodingStylePreference,
    ContextPackRequest,
    DispatchBrief,
    MemorySnippet,
    MemoryWriteRequest,
    MissionContextPacket,
    MissionWritebackPayload,
    PersonaSummary,
    RiskFlag,
    SuccessCriterion,
)


class IntegrationClientError(RuntimeError):
    pass


class IntegrationDeliveryUncertain(IntegrationClientError):
    """A POST may have been applied despite a missing/invalid acknowledgement."""


class PhiOSClient:
    endpoint_candidates = {
        'context_pack': ['/mission/context-pack', '/context/pack'],
        'writeback': ['/mission/writeback', '/memory/write'],
        'persona': '/persona/{persona_id}',
        'health': '/health',
    }

    def __init__(self) -> None:
        self.base_url = settings.agentora_phios_url.rstrip('/')
        self.enabled = settings.agentora_phios_enabled
        self.mock_mode = settings.agentora_integrations_mock
        self.timeout_seconds = settings.agentora_phios_timeout_seconds
        self.api_key = settings.agentora_phios_api_key

    def _headers(self) -> dict[str, str]:
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
            headers['X-API-Key'] = self.api_key
        return headers

    def _guard_enabled(self):
        if not self.enabled and not self.mock_mode:
            raise IntegrationClientError('PhiOS integration is disabled. Set AGENTORA_PHIOS_ENABLED=true or AGENTORA_INTEGRATIONS_MOCK=true.')

    def _mock_persona(self, persona_id: str) -> PersonaSummary:
        return PersonaSummary(
            id=persona_id,
            name='Mock Operator',
            role='principal engineer',
            style='precise and test-driven',
            goals=['ship safely', 'preserve operator experience'],
            constraints=['no vendoring external repos', 'keep flows optional'],
        )

    def _mock_packet(self, request: ContextPackRequest) -> MissionContextPacket:
        return MissionContextPacket(
            session_id='phios-mock-session-001',
            persona=self._mock_persona(request.persona_id),
            mission_title=request.mission_title or request.objective[:80],
            mission_objective=request.objective,
            repo=request.repo,
            operator_intent=request.operator_intent,
            summary=f'Mock packet for {request.repo}: {request.objective}',
            memory_snippets=[
                MemorySnippet(
                    id='mem-001',
                    text='Keep startup defaults unchanged unless integration is enabled.',
                    source='phios/mock',
                    score=0.91,
                    timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                )
            ],
            constraints=['Do not break current Streamlit nav', 'Use typed contracts'],
            recommended_next_actions=['Launch dry-run first', 'poll status before writeback'],
            coding_style_preferences=[CodingStylePreference(name='small functions', detail='keep orchestration steps explicit')],
            architectural_principles=[ArchitecturalPrinciple(name='thin bridge', rationale='avoid repo coupling')],
            risk_flags=[RiskFlag(name='schema_drift', severity='medium', mitigation='store raw payload snapshots')],
            success_criteria=[SuccessCriterion(name='status_refresh', metric='run refresh exposes phase/PR')],
            dispatch_brief=DispatchBrief(
                objective=request.objective,
                scope=['context injection', 'launch', 'poll', 'writeback'],
                non_goals=['deep execution engine changes'],
            ),
            generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def _post_first_success(self, paths: list[str], payload: dict) -> dict:
        """Try alternate routes only when the selected route is unsupported.

        Never send the same write to another route after a timeout, server
        error, or malformed success response: delivery may be ambiguous.
        """
        if not paths:
            raise IntegrationClientError('PhiOS endpoint call failed: no endpoints configured')
        for index, path in enumerate(paths):
            try:
                response = httpx.post(f'{self.base_url}{path}', json=payload, headers=self._headers(), timeout=self.timeout_seconds)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in (404, 405) and index < len(paths) - 1:
                    continue
                error_type = IntegrationDeliveryUncertain if status in (408, 425) or status >= 500 else IntegrationClientError
                raise error_type(f'PhiOS endpoint call failed: HTTP {status}') from exc
            except httpx.RequestError as exc:
                raise IntegrationDeliveryUncertain(f'PhiOS endpoint call failed: transport error ({type(exc).__name__})') from exc
            try:
                data = response.json()
            except ValueError as exc:
                raise IntegrationDeliveryUncertain('PhiOS endpoint call failed: invalid JSON response') from exc
            if not isinstance(data, dict):
                raise IntegrationDeliveryUncertain('PhiOS endpoint call failed: response must be a JSON object')
            return data
        raise IntegrationClientError('PhiOS endpoint call failed: no compatible endpoint')

    def get_persona(self, persona_id: str) -> PersonaSummary:
        self._guard_enabled()
        if self.mock_mode:
            return self._mock_persona(persona_id)
        try:
            path = self.endpoint_candidates['persona'].format(persona_id=persona_id)
            response = httpx.get(f'{self.base_url}{path}', headers=self._headers(), timeout=self.timeout_seconds)
            response.raise_for_status()
            return PersonaSummary.model_validate(response.json())
        except Exception as exc:
            raise IntegrationClientError(f'PhiOS persona fetch failed: {exc}') from exc

    def get_context_pack(self, request: ContextPackRequest) -> MissionContextPacket:
        self._guard_enabled()
        if self.mock_mode:
            return self._mock_packet(request)
        payload = request.model_dump(mode='json')
        raw = self._post_first_success(self.endpoint_candidates['context_pack'], payload)
        try:
            normalized = {
                'session_id': raw.get('session_id', ''),
                'persona': raw.get('persona') or self.get_persona(request.persona_id).model_dump(mode='json'),
                'mission_title': raw.get('mission_title') or request.mission_title or request.objective[:80],
                'mission_objective': raw.get('mission_objective') or raw.get('objective') or request.objective,
                'repo': raw.get('repo') or request.repo,
                'operator_intent': raw.get('operator_intent') or request.operator_intent,
                'summary': raw.get('summary', ''),
                'memory_snippets': raw.get('memory_snippets', []),
                'constraints': raw.get('constraints', []),
                'recommended_next_actions': raw.get('recommended_next_actions', []),
                'coding_style_preferences': raw.get('coding_style_preferences', []),
                'architectural_principles': raw.get('architectural_principles', []),
                'risk_flags': raw.get('risk_flags', []),
                'success_criteria': raw.get('success_criteria', []),
                'dispatch_brief': raw.get('dispatch_brief', {'objective': request.objective}),
                'generated_at': raw.get('generated_at') or datetime.now(timezone.utc).isoformat(),
            }
            return MissionContextPacket.model_validate(normalized)
        except Exception as exc:
            raise IntegrationClientError(f'PhiOS packet normalization failed: {exc}') from exc

    def write_memory(self, request: MemoryWriteRequest) -> dict:
        self._guard_enabled()
        if self.mock_mode:
            return {'ok': True, 'mode': 'mock', 'memory_id': 'phios-mock-memory-001'}
        return self._post_first_success(['/memory/write'], request.model_dump(mode='json'))

    def write_mission_result(self, payload: MissionWritebackPayload) -> dict:
        self._guard_enabled()
        if self.mock_mode:
            return {'ok': True, 'mode': 'mock', 'writeback_id': 'phios-mock-writeback-001'}
        return self._post_first_success(self.endpoint_candidates['writeback'], payload.model_dump(mode='json'))

    def _r4c_guard(self) -> str:
        """Only an explicitly configured local, authenticated R4b endpoint."""
        if not self.enabled or self.mock_mode or not settings.agentora_phios_writeback_v1_enabled:
            raise IntegrationClientError('PhiOS R4c writeback is not enabled')
        parsed = urlsplit(self.base_url)
        if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1'
                or parsed.username or parsed.password or parsed.path or parsed.query
                or parsed.fragment or parsed.port is None):
            raise IntegrationClientError('R4c requires an explicit 127.0.0.1 HTTP endpoint')
        if not self.api_key or len(self.api_key) < 32:
            raise IntegrationClientError('R4c requires a configured 32+ character API key')
        return self.base_url + '/api/v1/agentora/writeback'

    @staticmethod
    def _verified_receipt(data: object, expected: str, *, published: bool) -> dict:
        if not isinstance(data, dict) or data.get('operation_id') != expected:
            raise IntegrationDeliveryUncertain('PhiOS receipt operation identity mismatch')
        if published:
            if (data.get('ok') is not True or data.get('state') != 'published'
                    or not isinstance(data.get('receipt_id'), str) or not data['receipt_id']
                    or not isinstance(data.get('record_id'), str) or not data['record_id']):
                raise IntegrationDeliveryUncertain('PhiOS writeback lacks published receipt proof')
        elif data.get('state') not in {'pending', 'not_found', 'published'}:
            raise IntegrationClientError('PhiOS returned an invalid receipt state')
        return data

    def write_mission_result_v1(self, envelope: dict) -> dict:
        """Single POST, no alternate endpoint or implicit retry; require published proof."""
        endpoint = self._r4c_guard()
        if not isinstance(envelope, dict) or set(envelope) != {
                'protocol_version', 'operation_id', 'created_at_utc', 'payload'}:
            raise IntegrationClientError('R4c requires the complete persisted envelope')
        try:
            payload = envelope['payload']
            expected_id = operation_id(payload)
            canonical = canonical_envelope(payload, created_at_utc=envelope['created_at_utc'])
        except (ValueError, TypeError) as exc:
            raise IntegrationClientError('R4c envelope is invalid') from exc
        if (envelope['protocol_version'] != PROTOCOL
                or envelope['operation_id'] != expected_id
                or not isinstance(envelope['operation_id'], str)):
            raise IntegrationClientError('R4c operation identity mismatch')
        # Canonicalization is validated before any network call. The exactly
        # persisted outer envelope is dispatched, not rebuilt with a new time.
        if len(canonical.encode('utf-8')) > 32 * 1024:
            raise IntegrationClientError('R4c envelope exceeds protocol limit')
        try:
            response = httpx.post(
                endpoint, json=envelope,
                headers={'X-API-Key': self.api_key, 'Content-Type': 'application/json'},
                timeout=self.timeout_seconds,
            )
        except httpx.RequestError as exc:
            raise IntegrationDeliveryUncertain(
                f'PhiOS R4c transport uncertain ({type(exc).__name__})'
            ) from exc
        if response.status_code == 202:
            raise IntegrationDeliveryUncertain('PhiOS R4c receipt is pending')
        if response.status_code != 200:
            if response.status_code in (408, 425) or response.status_code >= 500:
                raise IntegrationDeliveryUncertain(
                    f'PhiOS R4c acknowledgement uncertain: HTTP {response.status_code}'
                )
            raise IntegrationClientError(f'PhiOS R4c rejected writeback: HTTP {response.status_code}')
        try:
            data = response.json()
        except ValueError as exc:
            raise IntegrationDeliveryUncertain('PhiOS R4c returned malformed success JSON') from exc
        return self._verified_receipt(data, expected_id, published=True)

    def writeback_receipt_status_v1(self, expected_id: str) -> dict:
        """GET-only reconciliation; never infer that 404 permits a POST retry."""
        endpoint = self._r4c_guard()
        if (not isinstance(expected_id, str) or len(expected_id) != 64
                or any(char not in '0123456789abcdef' for char in expected_id)):
            raise IntegrationClientError('R4c receipt status requires lowercase SHA-256 ID')
        try:
            response = httpx.get(
                f'{endpoint}/{expected_id}',
                headers={'X-API-Key': self.api_key},
                timeout=self.timeout_seconds,
            )
        except httpx.RequestError as exc:
            raise IntegrationClientError(
                f'PhiOS R4c receipt lookup failed ({type(exc).__name__})'
            ) from exc
        if response.status_code not in {200, 202, 404}:
            raise IntegrationClientError(
                f'PhiOS R4c receipt lookup failed: HTTP {response.status_code}'
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise IntegrationClientError('PhiOS R4c receipt lookup returned invalid JSON') from exc
        if response.status_code == 200:
            return self._verified_receipt(data, expected_id, published=True)
        result = self._verified_receipt(data, expected_id, published=False)
        expected_state = 'pending' if response.status_code == 202 else 'not_found'
        if result.get('state') != expected_state:
            raise IntegrationClientError('PhiOS R4c receipt lookup state disagrees with HTTP')
        return result

    def healthcheck(self) -> dict:
        if self.mock_mode:
            return {'ok': True, 'mode': 'mock', 'service': 'phios'}
        if not self.enabled:
            return {'ok': False, 'service': 'phios', 'detail': 'disabled'}
        try:
            response = httpx.get(f"{self.base_url}{self.endpoint_candidates['health']}", headers=self._headers(), timeout=self.timeout_seconds)
            response.raise_for_status()
            payload = response.json() if response.content else {}
            return {'ok': True, 'service': 'phios', 'payload': payload}
        except Exception as exc:
            return {'ok': False, 'service': 'phios', 'detail': str(exc)}
