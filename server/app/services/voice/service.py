from app.core.config import settings


def stt_from_wav(content: bytes) -> dict:
    if settings.agentora_use_mock_voice:
        return {'ok': True, 'transcript': 'mock transcript from audio'}
    if not settings.voice_enabled or not settings.whisper_cpp_path:
        return {'ok': False, 'error': 'stt_not_configured'}
    return {'ok': False, 'error': 'binary_hook_not_implemented'}


def tts_to_wav(text: str) -> tuple[dict, bytes]:
    if settings.agentora_use_mock_voice:
        return ({'ok': True, 'provider': 'mock'}, b'RIFFMOCKWAVE')
    if not settings.voice_enabled or not settings.piper_path or not settings.piper_voice_model_path:
        return ({'ok': False, 'error': 'tts_not_configured'}, b'')
    return ({'ok': False, 'error': 'binary_hook_not_implemented'}, b'')
