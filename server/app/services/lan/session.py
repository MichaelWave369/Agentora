import secrets

sessions: dict[str, dict] = {}


def create_join_code(run_id: int) -> dict:
    join_code = secrets.token_hex(3)
    host_token = secrets.token_hex(8)
    sessions[join_code] = {'run_id': run_id, 'host_token': host_token, 'members': []}
    return {'join_code': join_code, 'host_token': host_token}


def join_request(join_code: str, name: str) -> dict:
    s = sessions.get(join_code)
    if not s:
        return {'ok': False, 'error': 'invalid_code'}
    token = secrets.token_hex(8)
    s['members'].append({'name': name, 'token': token, 'approved': False})
    return {'ok': True, 'token': token}


def approve(join_code: str, host_token: str, token: str) -> dict:
    s = sessions.get(join_code)
    if not s or s['host_token'] != host_token:
        return {'ok': False, 'error': 'unauthorized'}
    for m in s['members']:
        if m['token'] == token:
            m['approved'] = True
            return {'ok': True}
    return {'ok': False, 'error': 'missing_member'}
