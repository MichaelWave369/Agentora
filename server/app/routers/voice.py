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


@router.get('/status')
def status():
    from app.core.config import settings
    configured = bool(settings.piper_path and settings.piper_voice_model_path)
    return {
        'voice_enabled': settings.voice_enabled,
        'piper_configured': configured,
        'whisper_configured': bool(settings.whisper_cpp_path),
        'install_command': 'brew install piper && piper --model <voice.onnx> --output_file demo.wav --text "hello"'
    }
