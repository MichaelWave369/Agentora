from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.integrations.phios_client import IntegrationClientError
from app.integrations.schemas import AgentCeptionJobStatus, AgentCeptionLaunchRequest, AgentCeptionLaunchResponse


class AgentCeptionClient:
    launch_path = '/api/dispatch/launch'
    job_status_path = '/api/dispatch/jobs/{job_id}'
    artifacts_path = '/api/dispatch/jobs/{job_id}/artifacts'
    health_paths = ['/health', '/api/health']

    def __init__(self) -> None:
        self.base_url = settings.agentora_agentception_url.rstrip('/')
        self.enabled = settings.agentora_agentception_enabled
        self.mock_mode = settings.agentora_integrations_mock
        self.timeout_seconds = settings.agentora_agentception_timeout_seconds
        self.api_key = settings.agentora_agentception_api_key

    def _headers(self) -> dict[str, str]:
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
            headers['X-API-Key'] = self.api_key
        return headers

    def _guard_enabled(self):
        if not self.enabled and not self.mock_mode:
            raise IntegrationClientError('AgentCeption integration is disabled. Set AGENTORA_AGENTCEPTION_ENABLED=true or AGENTORA_INTEGRATIONS_MOCK=true.')

    def launch_job(self, request: AgentCeptionLaunchRequest) -> AgentCeptionLaunchResponse:
        self._guard_enabled()
        if self.mock_mode:
            return AgentCeptionLaunchResponse(
                job_id='ac-mock-job-001',
                status='queued',
                message='Mock dispatch accepted',
                launch_url=f'{self.base_url}/jobs/ac-mock-job-001',
            )
        url = f'{self.base_url}{self.launch_path}'
        try:
            response = httpx.post(url, json=request.model_dump(), headers=self._headers(), timeout=self.timeout_seconds)
            response.raise_for_status()
            return AgentCeptionLaunchResponse.model_validate(response.json())
        except Exception as exc:
            raise IntegrationClientError(f'AgentCeption launch failed: {exc}') from exc

    def get_job_status(self, job_id: str) -> AgentCeptionJobStatus:
        self._guard_enabled()
        if self.mock_mode:
            return AgentCeptionJobStatus(
                job_id=job_id,
                status='running',
                phase='planning',
                branch='feat/mock-integration-bridge',
                pr_url='https://example.com/mock/pr/1',
                issue_urls=['https://example.com/mock/issues/1'],
                artifact_urls=['https://example.com/mock/artifacts/log.txt'],
                updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                summary='Mock AgentCeption run is progressing through plan and worktree phases.',
            )
        url = f"{self.base_url}{self.job_status_path.format(job_id=job_id)}"
        try:
            response = httpx.get(url, headers=self._headers(), timeout=self.timeout_seconds)
            response.raise_for_status()
            return AgentCeptionJobStatus.model_validate(response.json())
        except Exception as exc:
            raise IntegrationClientError(f'AgentCeption job status failed: {exc}') from exc

    def list_job_artifacts(self, job_id: str) -> dict:
        self._guard_enabled()
        if self.mock_mode:
            return {'job_id': job_id, 'artifacts': ['https://example.com/mock/artifacts/log.txt']}
        url = f"{self.base_url}{self.artifacts_path.format(job_id=job_id)}"
        try:
            response = httpx.get(url, headers=self._headers(), timeout=self.timeout_seconds)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise IntegrationClientError(f'AgentCeption artifacts failed: {exc}') from exc

    def healthcheck(self) -> dict:
        if self.mock_mode:
            return {'ok': True, 'mode': 'mock', 'service': 'agentception'}
        if not self.enabled:
            return {'ok': False, 'service': 'agentception', 'detail': 'disabled'}
        for path in self.health_paths:
            try:
                response = httpx.get(f'{self.base_url}{path}', headers=self._headers(), timeout=self.timeout_seconds)
                response.raise_for_status()
                payload = response.json() if response.content else {}
                return {'ok': True, 'service': 'agentception', 'payload': payload}
            except Exception:
                continue
        return {'ok': False, 'service': 'agentception', 'detail': 'health endpoint unavailable'}
