from datetime import datetime, timezone

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
        last_exc: Exception | None = None
        for path in paths:
            try:
                response = httpx.post(f'{self.base_url}{path}', json=payload, headers=self._headers(), timeout=self.timeout_seconds)
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_exc = exc
        raise IntegrationClientError(f'PhiOS endpoint call failed: {last_exc}')

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
