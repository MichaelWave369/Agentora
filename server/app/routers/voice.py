from fastapi import APIRouter, UploadFile, File
from fastapi.responses import Response

from app.services.voice.service import stt_from_wav, tts_to_wav

router = APIRouter(prefix='/api/voice', tags=['voice'])


@router.post('/stt')
def stt(file: UploadFile = File(...)):
    return stt_from_wav(file.file.read())


@router.post('/tts')
def tts(payload: dict):
    meta, wav = tts_to_wav(payload.get('text', ''))
    if not meta.get('ok'):
        return meta
    return Response(content=wav, media_type='audio/wav')
