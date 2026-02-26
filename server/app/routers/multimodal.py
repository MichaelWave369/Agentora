import json
from fastapi import APIRouter, Depends, UploadFile, File
from sqlmodel import Session

from app.db import get_session
from app.models import Attachment, AttachmentExtract
from app.services.multimodal.service import store_upload, extract_pdf_text

router = APIRouter(tags=['multimodal'])


@router.post('/api/runs/{run_id}/attachments')
def upload_attachment(run_id: int, file: UploadFile = File(...), session: Session = Depends(get_session)):
    data = file.file.read()
    path, sha = store_upload(run_id, file.filename, data)
    a = Attachment(run_id=run_id, filename=file.filename, mime=file.content_type or 'application/octet-stream', sha256=sha, path=path, meta_json='{}')
    session.add(a)
    session.commit()
    session.refresh(a)
    extract = ''
    if (file.content_type or '').lower() == 'application/pdf' or file.filename.lower().endswith('.pdf'):
        extract = extract_pdf_text(path)
        session.add(AttachmentExtract(attachment_id=a.id, text=extract))
        session.commit()
    return {'ok': True, 'attachment_id': a.id, 'extract_preview': extract[:500]}
