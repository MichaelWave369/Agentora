"""Tests for PhiOS endpoint fallback; all HTTP transport is mocked."""
import httpx
import pytest

from app.integrations.phios_client import IntegrationClientError, PhiOSClient


PATHS = ['/mission/writeback', '/memory/write']


def _client():
    client = PhiOSClient()
    client.base_url = 'http://127.0.0.1:8090'
    client.api_key = ''
    return client


def _response(url, status, payload=None):
    request = httpx.Request('POST', url)
    if payload is None:
        payload = {'ok': True}
    return httpx.Response(status, request=request, json=payload)


@pytest.mark.parametrize('missing_status', [404, 405])
def test_fallback_only_on_unsupported_route(monkeypatch, missing_status):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs['json']))
        return _response(url, missing_status if len(calls) == 1 else 200)

    monkeypatch.setattr(httpx, 'post', post)
    result = _client()._post_first_success(PATHS, {'task_id': 'same-task'})
    assert result == {'ok': True}
    assert [url.rsplit('8090', 1)[1] for url, _ in calls] == PATHS
    assert all(payload == {'task_id': 'same-task'} for _, payload in calls)


@pytest.mark.parametrize('status', [400, 401, 403, 409, 422, 429, 500, 503])
def test_non_routing_http_failure_does_not_post_second_time(monkeypatch, status):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        return _response(url, status, {'error': 'request rejected'})

    monkeypatch.setattr(httpx, 'post', post)
    with pytest.raises(IntegrationClientError, match=f'HTTP {status}'):
        _client()._post_first_success(PATHS, {'task_id': 'task-1'})
    assert len(calls) == 1


@pytest.mark.parametrize('kind', [httpx.TimeoutException, httpx.ConnectError])
def test_unknown_delivery_state_does_not_retry(monkeypatch, kind):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        raise kind('transport failure', request=httpx.Request('POST', url))

    monkeypatch.setattr(httpx, 'post', post)
    with pytest.raises(IntegrationClientError, match='transport error'):
        _client()._post_first_success(PATHS, {'task_id': 'task-1'})
    assert len(calls) == 1


@pytest.mark.parametrize('kind', ['invalid-json', 'json-array', 'empty'])
def test_invalid_success_response_does_not_retry(monkeypatch, kind):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        if kind == 'json-array':
            return _response(url, 200, [1, 2])
        if kind == 'empty':
            return httpx.Response(204, request=httpx.Request('POST', url))
        return httpx.Response(200, request=httpx.Request('POST', url), content=b'bad-json')

    monkeypatch.setattr(httpx, 'post', post)
    with pytest.raises(IntegrationClientError, match='invalid JSON response|JSON object'):
        _client()._post_first_success(PATHS, {'task_id': 'task-1'})
    assert len(calls) == 1


def test_both_routes_unavailable_raises_without_third_post(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        return _response(url, 404)

    monkeypatch.setattr(httpx, 'post', post)
    with pytest.raises(IntegrationClientError, match='HTTP 404'):
        _client()._post_first_success(PATHS, {'task_id': 'task-1'})
    assert len(calls) == 2


def test_empty_configured_endpoint_list_fails_closed(monkeypatch):
    def unexpected_post(*args, **kwargs):
        raise AssertionError('No network call should happen for an empty path list')

    monkeypatch.setattr(httpx, 'post', unexpected_post)
    with pytest.raises(IntegrationClientError, match='no endpoints configured'):
        _client()._post_first_success([], {'task_id': 'task-1'})
