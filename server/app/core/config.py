from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_prefix='', extra='ignore')

    app_name: str = 'Agentora'
    database_url: str = Field(default='sqlite:///server/data/agentora.db', alias='AGENTORA_DATABASE_URL')
    ollama_url: str = Field(default='http://localhost:11434', alias='OLLAMA_URL')
    ollama_model_default: str = Field(default='llama3.1', alias='OLLAMA_MODEL_DEFAULT')
    agentora_vision_model_fallback: str = Field(default='llava:latest', alias='AGENTORA_VISION_MODEL_FALLBACK')
    agentora_use_mock_ollama: bool = Field(default=False, alias='AGENTORA_USE_MOCK_OLLAMA')
    agentora_use_mock_voice: bool = Field(default=False, alias='AGENTORA_USE_MOCK_VOICE')
    agentora_network_mode: str = Field(default='localhost_only', alias='AGENTORA_NETWORK_MODE')
    agentora_allowed_hosts: str = Field(default='localhost,127.0.0.1', alias='AGENTORA_ALLOWED_HOSTS')
    agentora_parallel_limit: int = Field(default=4, alias='AGENTORA_PARALLEL_LIMIT')
    agentora_default_max_turns: int = Field(default=8, alias='AGENTORA_DEFAULT_MAX_TURNS')
    agentora_default_max_seconds: int = Field(default=90, alias='AGENTORA_DEFAULT_MAX_SECONDS')
    agentora_enable_http_fetch: bool = Field(default=False, alias='AGENTORA_ENABLE_HTTP_FETCH')
    agentora_enable_code_exec: bool = Field(default=False, alias='AGENTORA_ENABLE_CODE_EXEC')
    agentora_enable_lan_mode: bool = Field(default=False, alias='AGENTORA_ENABLE_LAN_MODE')
    agentora_encryption_key: str | None = Field(default=None, alias='AGENTORA_ENCRYPTION_KEY')
    voice_enabled: bool = Field(default=False, alias='VOICE_ENABLED')
    whisper_cpp_path: str = Field(default='', alias='WHISPER_CPP_PATH')
    piper_path: str = Field(default='', alias='PIPER_PATH')
    piper_voice_model_path: str = Field(default='', alias='PIPER_VOICE_MODEL_PATH')

    @property
    def allowed_hosts(self) -> list[str]:
        return [h.strip() for h in self.agentora_allowed_hosts.split(',') if h.strip()]


settings = Settings()
