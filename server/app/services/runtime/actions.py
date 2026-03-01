from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import shutil
import subprocess

import requests
from sqlmodel import Session, select

from app.core.config import settings
from app.models import ActionApproval, ActionArtifact, ActionExecution, ActionRequest, PolicyRule
from app.services.runtime.router import route_worker_job
from app.services.runtime.trace import add_trace


def _within_allowed_path(path: str) -> bool:
    p = Path(path).resolve()
    for blocked in settings.blocked_path_roots:
        if blocked and str(p).startswith(str(Path(blocked).resolve())):
            return False
    if not settings.allowed_path_roots:
        return False
    return any(str(p).startswith(str(Path(root).resolve())) for root in settings.allowed_path_roots)


def _domain_allowed(url: str) -> bool:
    domain = (urlparse(url).hostname or '').lower()
    if not domain:
        return False
    if any(domain == d.lower() or domain.endswith('.' + d.lower()) for d in settings.blocked_domains):
        return False
    if settings.allowed_domains:
        return any(domain == d.lower() or domain.endswith('.' + d.lower()) for d in settings.allowed_domains)
    return True


def evaluate_policy(session: Session, action_class: str, tool_name: str, agent_role: str, params: dict) -> tuple[str, str]:
    rule = session.exec(select(PolicyRule).where(PolicyRule.enabled == True, PolicyRule.action_class == action_class, PolicyRule.tool_name == tool_name)).first()
    if rule:
        return rule.approval_level, f'rule:{rule.id}'

    if action_class == 'desktop':
        path = str(params.get('path') or params.get('src') or params.get('dst') or '')
        if path and not _within_allowed_path(path):
            return 'deny', 'path_outside_allowed_roots'
    if action_class == 'browser':
        url = str(params.get('url') or '')
        if url and not _domain_allowed(url):
            return 'deny', 'domain_blocked_or_not_allowlisted'

    if tool_name in {'desktop_write_text', 'desktop_move', 'desktop_copy', 'desktop_rename', 'desktop_run_app', 'desktop_shell', 'browser_download'}:
        return settings.agentora_action_require_approval_default, 'sensitive_default'
    return 'auto_allow', 'safe_default'


def create_action_request(session: Session, run_id: int, agent_id: int, action_class: str, tool_name: str, params: dict, subgoal_id: int | None = None, requested_worker: bool = False, agent_role: str = '') -> ActionRequest:
    decision, reason = evaluate_policy(session, action_class=action_class, tool_name=tool_name, agent_role=agent_role, params=params)
    req = ActionRequest(
        run_id=run_id,
        agent_id=agent_id,
        subgoal_id=subgoal_id,
        action_class=action_class,
        tool_name=tool_name,
        params_json=json.dumps(params),
        policy_decision=decision,
        status='pending' if decision in {'ask_once', 'always_ask'} else ('denied' if decision == 'deny' else 'approved'),
        requires_approval=decision in {'ask_once', 'always_ask'},
        requested_worker=requested_worker,
    )
    session.add(req)
    session.commit()
    session.refresh(req)

    ev = 'desktop_action_requested' if action_class == 'desktop' else 'browser_action_requested'
    add_trace(session, run_id, ev, {'action_id': req.id, 'tool_name': tool_name, 'params': params, 'policy_decision': decision, 'policy_reason': reason}, agent_id=agent_id)
    if req.status == 'pending':
        add_trace(session, run_id, 'approval_requested', {'action_id': req.id, 'tool_name': tool_name, 'policy_decision': decision}, agent_id=agent_id)
    if req.status == 'denied':
        add_trace(session, run_id, 'policy_blocked', {'action_id': req.id, 'reason': reason, 'tool_name': tool_name}, agent_id=agent_id)
    session.commit()
    return req


def _desktop_execute(tool_name: str, params: dict) -> dict:
    if tool_name == 'desktop_list_dir':
        path = params.get('path', '.')
        p = Path(path)
        return {'ok': True, 'items': sorted([x.name for x in p.iterdir()])[:400]}
    if tool_name == 'desktop_read_text':
        path = params['path']
        return {'ok': True, 'text': Path(path).read_text(encoding='utf-8')[:5000]}
    if tool_name == 'desktop_write_text':
        path = params['path']
        content = params.get('content', '')
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(content, encoding='utf-8')
        return {'ok': True, 'bytes': len(content.encode('utf-8'))}
    if tool_name == 'desktop_move':
        shutil.move(params['src'], params['dst'])
        return {'ok': True}
    if tool_name == 'desktop_copy':
        shutil.copy2(params['src'], params['dst'])
        return {'ok': True}
    if tool_name == 'desktop_rename':
        Path(params['src']).rename(params['dst'])
        return {'ok': True}
    if tool_name == 'desktop_run_app':
        app = params.get('app', '')
        if settings.allowed_apps and app not in settings.allowed_apps:
            return {'ok': False, 'error': 'app_not_allowlisted'}
        proc = subprocess.run([app] + list(params.get('args', [])), capture_output=True, text=True, timeout=20)
        return {'ok': proc.returncode == 0, 'returncode': proc.returncode, 'stdout': proc.stdout[:1200], 'stderr': proc.stderr[:1200]}
    if tool_name == 'desktop_shell':
        cmd = params.get('command', '')
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)
        return {'ok': proc.returncode == 0, 'returncode': proc.returncode, 'stdout': proc.stdout[:1200], 'stderr': proc.stderr[:1200]}
    return {'ok': False, 'error': 'unknown_desktop_tool'}


def _browser_execute(tool_name: str, params: dict) -> dict:
    url = params.get('url', '')
    if url and not _domain_allowed(url):
        return {'ok': False, 'error': 'domain_not_allowed'}
    if tool_name in {'browser_open_url', 'browser_extract_text', 'browser_page_summary'}:
        r = requests.get(url, timeout=8)
        text = r.text
        if tool_name == 'browser_open_url':
            return {'ok': r.ok, 'status_code': r.status_code, 'url': url}
        if tool_name == 'browser_extract_text':
            return {'ok': r.ok, 'text': text[:5000]}
        return {'ok': r.ok, 'summary': text[:1000], 'status_code': r.status_code}
    if tool_name == 'browser_download':
        r = requests.get(url, timeout=12)
        out = params.get('output_path', 'server/data/artifacts/download.bin')
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(r.content)
        return {'ok': r.ok, 'output_path': out, 'bytes': len(r.content)}
    if tool_name in {'browser_navigate', 'browser_search', 'browser_click', 'browser_fill_form'}:
        return {'ok': True, 'note': f'{tool_name} simulated via bounded http runtime', 'params': params}
    return {'ok': False, 'error': 'unknown_browser_tool'}


def execute_action_request(session: Session, action_id: int, approved_by: str = 'system') -> ActionExecution:
    req = session.get(ActionRequest, action_id)
    if not req:
        raise ValueError('action_not_found')
    if req.status == 'denied':
        raise ValueError('action_denied')

    params = json.loads(req.params_json or '{}')
    if req.status == 'pending':
        raise ValueError('approval_required')

    exec_row = ActionExecution(action_request_id=req.id or 0, run_id=req.run_id, status='running', execution_mode='local')
    session.add(exec_row)
    session.commit()
    session.refresh(exec_row)

    use_worker = req.requested_worker and req.tool_name in {'browser_extract_text', 'browser_page_summary', 'browser_download', 'desktop_shell'}
    if use_worker:
        add_trace(session, req.run_id, 'action_worker_route_selected', {'action_id': req.id, 'tool_name': req.tool_name}, agent_id=req.agent_id)
        job = route_worker_job(session, 'long_tool_job', {'run_id': req.run_id, 'action_id': req.id, 'tool_name': req.tool_name, 'params': params}, priority=4)
        if job.used_fallback_local:
            add_trace(session, req.run_id, 'action_worker_fallback', {'action_id': req.id, 'reason': job.error or 'worker_unavailable'}, agent_id=req.agent_id)
        else:
            exec_row.execution_mode = 'worker'
            exec_row.worker_job_id = job.id
            add_trace(session, req.run_id, 'action_worker_completed', {'action_id': req.id, 'worker_job_id': job.id, 'status': job.status}, agent_id=req.agent_id)

    if req.action_class == 'desktop':
        result = _desktop_execute(req.tool_name, params)
    else:
        result = _browser_execute(req.tool_name, params)

    exec_row.status = 'done' if result.get('ok') else 'failed'
    exec_row.finished_at = datetime.utcnow()
    exec_row.result_json = json.dumps(result)
    exec_row.error = '' if result.get('ok') else str(result.get('error', 'action_failed'))
    session.add(exec_row)

    req.status = 'executed' if result.get('ok') else 'failed'
    req.decided_at = datetime.utcnow()
    session.add(req)

    if 'output_path' in result:
        session.add(ActionArtifact(run_id=req.run_id, action_execution_id=exec_row.id or 0, kind='file', path=result['output_path'], content_preview='', meta_json=json.dumps({'tool_name': req.tool_name})))
    elif 'text' in result:
        session.add(ActionArtifact(run_id=req.run_id, action_execution_id=exec_row.id or 0, kind='text', path='', content_preview=str(result.get('text', ''))[:300], meta_json=json.dumps({'tool_name': req.tool_name})))

    add_trace(session, req.run_id, 'desktop_action_executed' if req.action_class == 'desktop' else 'browser_action_executed', {'action_id': req.id, 'tool_name': req.tool_name, 'status': exec_row.status, 'execution_mode': exec_row.execution_mode}, agent_id=req.agent_id)
    session.commit()
    session.refresh(exec_row)
    return exec_row


def approve_action(session: Session, action_id: int, decided_by: str = 'user', reason: str = '') -> ActionExecution:
    req = session.get(ActionRequest, action_id)
    if not req:
        raise ValueError('action_not_found')
    req.status = 'approved'
    req.decided_at = datetime.utcnow()
    session.add(req)
    session.add(ActionApproval(action_request_id=req.id or 0, decision='granted', decided_by=decided_by, reason=reason))
    add_trace(session, req.run_id, 'approval_granted', {'action_id': req.id, 'tool_name': req.tool_name, 'decided_by': decided_by}, agent_id=req.agent_id)
    add_trace(session, req.run_id, 'desktop_action_approved' if req.action_class == 'desktop' else 'browser_action_requested', {'action_id': req.id}, agent_id=req.agent_id)
    session.commit()
    return execute_action_request(session, action_id, approved_by=decided_by)


def deny_action(session: Session, action_id: int, decided_by: str = 'user', reason: str = '') -> ActionRequest:
    req = session.get(ActionRequest, action_id)
    if not req:
        raise ValueError('action_not_found')
    req.status = 'denied'
    req.decided_at = datetime.utcnow()
    session.add(req)
    session.add(ActionApproval(action_request_id=req.id or 0, decision='denied', decided_by=decided_by, reason=reason))
    add_trace(session, req.run_id, 'approval_denied', {'action_id': req.id, 'reason': reason}, agent_id=req.agent_id)
    add_trace(session, req.run_id, 'desktop_action_denied' if req.action_class == 'desktop' else 'policy_blocked', {'action_id': req.id, 'reason': reason}, agent_id=req.agent_id)
    session.commit()
    return req
