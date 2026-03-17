from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.integrations.schemas import (
    ContextPackRequest,
    ContextPackResponse,
    MemorySnippet,
    MemoryWriteRequest,
    PersonaSummary,
)


class IntegrationClientError(RuntimeError):
    pass


class PhiOSClient:
    persona_path = '/persona/{persona_id}'
    context_pack_path = '/context/pack'
    memory_write_path = '/memory/write'
    health_path = '/health'

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
            goals=['Ship reliable integrations', 'Keep UX stable'],
            constraints=['No repo vendoring', 'Prefer reversible changes'],
        )

    def get_persona(self, persona_id: str) -> PersonaSummary:
        self._guard_enabled()
        if self.mock_mode:
            return self._mock_persona(persona_id)
        url = f"{self.base_url}{self.persona_path.format(persona_id=persona_id)}"
        try:
            response = httpx.get(url, headers=self._headers(), timeout=self.timeout_seconds)
            response.raise_for_status()
            return PersonaSummary.model_validate(response.json())
        except Exception as exc:
            raise IntegrationClientError(f'PhiOS persona fetch failed: {exc}') from exc

    def get_context_pack(self, request: ContextPackRequest) -> ContextPackResponse:
        self._guard_enabled()
        if self.mock_mode:
            persona = self._mock_persona(request.persona_id)
            snippets = [
                MemorySnippet(
                    id='mem-001',
                    text='Operator prefers incremental rollouts and fast rollback paths.',
                    source='phios/mock',
                    score=0.92,
                    timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                ),
                MemorySnippet(
                    id='mem-002',
                    text='Prioritize preserving Agentora startup flows.',
                    source='phios/mock',
                    score=0.88,
                    timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc),
                ),
            ]
            return ContextPackResponse(
                persona=persona,
                session_id='phios-mock-session-001',
                summary=f'Mock context for {request.repo}: {request.objective}',
                memory_snippets=snippets,
                constraints=['Do not break UX', 'Keep integrations optional'],
                recommended_next_actions=['Launch dry run first', 'Confirm PR output wiring'],
            )
        url = f'{self.base_url}{self.context_pack_path}'
        try:
            response = httpx.post(url, json=request.model_dump(), headers=self._headers(), timeout=self.timeout_seconds)
            response.raise_for_status()
            return ContextPackResponse.model_validate(response.json())
        except Exception as exc:
            raise IntegrationClientError(f'PhiOS context pack fetch failed: {exc}') from exc

    def write_memory(self, request: MemoryWriteRequest) -> dict:
        self._guard_enabled()
        if self.mock_mode:
            return {'ok': True, 'mode': 'mock', 'memory_id': 'phios-mock-memory-001'}
        url = f'{self.base_url}{self.memory_write_path}'
        try:
            response = httpx.post(url, json=request.model_dump(), headers=self._headers(), timeout=self.timeout_seconds)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise IntegrationClientError(f'PhiOS write memory failed: {exc}') from exc

    def healthcheck(self) -> dict:
        if self.mock_mode:
            return {'ok': True, 'mode': 'mock', 'service': 'phios'}
        if not self.enabled:
            return {'ok': False, 'service': 'phios', 'detail': 'disabled'}
        url = f'{self.base_url}{self.health_path}'
        try:
            response = httpx.get(url, headers=self._headers(), timeout=self.timeout_seconds)
            response.raise_for_status()
            payload = response.json() if response.content else {}
            return {'ok': True, 'service': 'phios', 'payload': payload}
        except Exception as exc:
            return {'ok': False, 'service': 'phios', 'detail': str(exc)}
