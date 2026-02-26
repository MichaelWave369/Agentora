import json
from pathlib import Path
import yaml
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.db import get_session
from app.models import InstalledTemplate
from app.services.marketplace.service import list_marketplace_templates, install_template, semver_tuple

router = APIRouter(tags=['marketplace'])


@router.get('/api/marketplace/templates')
def marketplace_templates(session: Session = Depends(get_session)):
    installed = {t.name: t for t in session.exec(select(InstalledTemplate))}
    rows = []
    for t in list_marketplace_templates():
        ins = installed.get(t['name'])
        update = bool(ins and semver_tuple(t['version']) > semver_tuple(ins.version))
        rows.append({**t, 'installed_version': ins.version if ins else None, 'update_available': update})
    return {'templates': rows}


@router.post('/api/marketplace/install')
def marketplace_install(payload: dict, session: Session = Depends(get_session)):
    name = payload['name']
    version = payload['version']
    p = install_template(name, version)
    data = yaml.safe_load(Path(p).read_text(encoding='utf-8'))
    row = InstalledTemplate(name=data['name'], version=data['version'], description=data.get('description', ''), tags_json=json.dumps(data.get('tags', [])), yaml_path=str(p))
    session.add(row)
    session.commit()
    return {'ok': True, 'path': str(p)}


@router.post('/api/marketplace/update')
def marketplace_update(payload: dict, session: Session = Depends(get_session)):
    return marketplace_install(payload, session)


@router.get('/api/templates/installed')
def installed(session: Session = Depends(get_session)):
    return list(session.exec(select(InstalledTemplate)))


@router.get('/api/templates/{template_id}/yaml')
def template_yaml(template_id: int, session: Session = Depends(get_session)):
    t = session.get(InstalledTemplate, template_id)
    if not t:
        raise HTTPException(404, 'not found')
    return {'yaml_text': Path(t.yaml_path).read_text(encoding='utf-8')}


@router.post('/api/templates/import')
def template_import(file: UploadFile = File(...), session: Session = Depends(get_session)):
    content = file.file.read()
    data = yaml.safe_load(content.decode('utf-8'))
    out = Path('server/data/user_templates')
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{data['name']}@{data['version']}.yaml"
    p.write_bytes(content)
    row = InstalledTemplate(name=data['name'], version=data['version'], description=data.get('description', ''), tags_json=json.dumps(data.get('tags', [])), yaml_path=str(p), source='import')
    session.add(row)
    session.commit()
    return {'ok': True, 'id': row.id}


@router.get('/api/templates/export/{template_id}')
def template_export(template_id: int, session: Session = Depends(get_session)):
    t = session.get(InstalledTemplate, template_id)
    if not t:
        raise HTTPException(404, 'not found')
    return FileResponse(t.yaml_path, media_type='text/yaml', filename=Path(t.yaml_path).name)
