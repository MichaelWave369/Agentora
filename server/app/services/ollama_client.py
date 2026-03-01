from collections.abc import AsyncGenerator
import json
import base64
import hashlib
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

    async def chat_structured(self, model: str, system: str, prompt: str, schema: dict) -> dict:
        if settings.agentora_use_mock_ollama:
            done = 'no final answer' not in prompt.lower()
            return {
                'thought': 'mock structured planner',
                'need_memory': True,
                'memory_queries': ['key context'],
                'tool_calls': [],
                'final': 'MOCK structured response',
                'handoff': '',
                'done': done,
            }
        ensure_url_allowed(settings.ollama_url)
        payload = {
            'model': model,
            'stream': False,
            'format': schema,
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': prompt},
            ],
        }
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f'{settings.ollama_url}/api/chat', json=payload)
            r.raise_for_status()
            content = r.json().get('message', {}).get('content', '{}')
            if isinstance(content, dict):
                return content
            return json.loads(content)

    async def chat_with_tools(self, model: str, system: str, prompt: str, tools: list[dict]) -> dict:
        if settings.agentora_use_mock_ollama:
            return {'message': {'content': f'MOCK TOOL CHAT: {prompt[:100]}', 'tool_calls': []}}
        ensure_url_allowed(settings.ollama_url)
        payload = {
            'model': model,
            'stream': False,
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': prompt},
            ],
            'tools': tools,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f'{settings.ollama_url}/api/chat', json=payload)
            r.raise_for_status()
            return r.json()

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if settings.agentora_use_mock_ollama:
            out = []
            for t in texts:
                digest = hashlib.sha256(t.encode('utf-8')).digest()
                out.append([((b / 255.0) * 2 - 1) for b in digest[:32]])
            return out
        ensure_url_allowed(settings.ollama_url)
        async with httpx.AsyncClient(timeout=120) as client:
            vecs: list[list[float]] = []
            for text in texts:
                r = await client.post(
                    f'{settings.ollama_url}/api/embeddings',
                    json={'model': settings.agentora_embed_model, 'prompt': text},
                )
                r.raise_for_status()
                vecs.append(r.json().get('embedding', []))
            return vecs
