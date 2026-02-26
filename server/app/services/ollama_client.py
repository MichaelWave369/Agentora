from collections.abc import AsyncGenerator
import json
import base64
import httpx

from app.core.config import settings
from app.core.security import ensure_url_allowed


class OllamaClient:
    async def list_models(self) -> list[str]:
        if settings.agentora_use_mock_ollama:
            return [settings.ollama_model_default, settings.agentora_vision_model_fallback, 'mock-mini']
        ensure_url_allowed(settings.ollama_url)
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(f'{settings.ollama_url}/api/tags')
            r.raise_for_status()
            return [m['name'] for m in r.json().get('models', [])]

    async def stream_chat(self, model: str, system: str, prompt: str, image_paths: list[str] | None = None) -> AsyncGenerator[str, None]:
        if settings.agentora_use_mock_ollama:
            text = f'MOCK[{model}] {prompt[:80]}'
            for token in text.split(' '):
                yield token + ' '
            return
        ensure_url_allowed(settings.ollama_url)
        images = []
        for p in image_paths or []:
            with open(p, 'rb') as f:
                images.append(base64.b64encode(f.read()).decode('utf-8'))
        payload = {
            'model': model,
            'stream': True,
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt, 'images': images}],
        }
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream('POST', f'{settings.ollama_url}/api/chat', json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line:
                        try:
                            obj = json.loads(line)
                            msg = obj.get('message', {}).get('content', '')
                            if msg:
                                yield msg
                        except Exception:
                            yield line
