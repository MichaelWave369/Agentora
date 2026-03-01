from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
import json


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_prefix='', extra='ignore')

    app_name: str = 'Agentora'
    agentora_version: str = Field(default='0.9.6', alias='AGENTORA_VERSION')
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

    agentora_lan_discovery_enabled: bool = Field(default=True, alias='AGENTORA_LAN_DISCOVERY_ENABLED')
    agentora_gathering_encryption_key: str = Field(default='', alias='AGENTORA_GATHERING_ENCRYPTION_KEY')

    agentora_embed_model: str = Field(default='embeddinggemma', alias='AGENTORA_EMBED_MODEL')
    agentora_tool_model: str = Field(default='qwen3:14b', alias='AGENTORA_TOOL_MODEL')
    agentora_chat_model: str = Field(default='gemma3:12b', alias='AGENTORA_CHAT_MODEL')
    agentora_worker_urls: str = Field(default='', alias='AGENTORA_WORKER_URLS')
    agentora_capsule_top_k: int = Field(default=6, alias='AGENTORA_CAPSULE_TOP_K')
    agentora_max_tool_steps: int = Field(default=4, alias='AGENTORA_MAX_TOOL_STEPS')

    agentora_vision_model: str = Field(default='', alias='AGENTORA_VISION_MODEL')
    agentora_extraction_model: str = Field(default='', alias='AGENTORA_EXTRACTION_MODEL')
    agentora_enable_model_role_routing: bool = Field(default=True, alias='AGENTORA_ENABLE_MODEL_ROLE_ROUTING')
    agentora_allowed_tool_names: str = Field(default='', alias='AGENTORA_ALLOWED_TOOL_NAMES')
    agentora_blocked_tool_names: str = Field(default='', alias='AGENTORA_BLOCKED_TOOL_NAMES')
    agentora_http_allowlist: str = Field(default='', alias='AGENTORA_HTTP_ALLOWLIST')
    agentora_file_write_root: str = Field(default='server/data/artifacts', alias='AGENTORA_FILE_WRITE_ROOT')
    agentora_max_worker_retries: int = Field(default=2, alias='AGENTORA_MAX_WORKER_RETRIES')
    agentora_enable_layered_memory: bool = Field(default=True, alias='AGENTORA_ENABLE_LAYERED_MEMORY')
    agentora_context_top_k: int = Field(default=8, alias='AGENTORA_CONTEXT_TOP_K')
    agentora_max_active_contexts: int = Field(default=6, alias='AGENTORA_MAX_ACTIVE_CONTEXTS')
    agentora_context_min_score: float = Field(default=0.25, alias='AGENTORA_CONTEXT_MIN_SCORE')
    agentora_context_layer_budgets: str = Field(default='{"L0_HOT":2,"L1_SHORT":3,"L2_SESSION":2,"L3_DURABLE":2,"L4_SPARSE":2}', alias='AGENTORA_CONTEXT_LAYER_BUDGETS')
    agentora_memory_decay_short: float = Field(default=0.85, alias='AGENTORA_MEMORY_DECAY_SHORT')
    agentora_memory_decay_medium: float = Field(default=0.95, alias='AGENTORA_MEMORY_DECAY_MEDIUM')
    agentora_memory_decay_long: float = Field(default=0.995, alias='AGENTORA_MEMORY_DECAY_LONG')
    agentora_memory_layer_weights: str = Field(default='{"L0_HOT":1.25,"L1_SHORT":1.0,"L2_SESSION":0.92,"L3_DURABLE":0.88,"L4_SPARSE":0.8,"L5_COLD":0.35}', alias='AGENTORA_MEMORY_LAYER_WEIGHTS')
    agentora_memory_promotion_threshold: float = Field(default=0.68, alias='AGENTORA_MEMORY_PROMOTION_THRESHOLD')
    agentora_memory_demotion_threshold: float = Field(default=0.22, alias='AGENTORA_MEMORY_DEMOTION_THRESHOLD')
    agentora_cold_archive_after_days: int = Field(default=30, alias='AGENTORA_COLD_ARCHIVE_AFTER_DAYS')
    agentora_memory_maintenance_interval: int = Field(default=3600, alias='AGENTORA_MEMORY_MAINTENANCE_INTERVAL')
    agentora_enable_graph_rerank: bool = Field(default=True, alias='AGENTORA_ENABLE_GRAPH_RERANK')
    agentora_enable_adaptive_refinement: bool = Field(default=True, alias='AGENTORA_ENABLE_ADAPTIVE_REFINEMENT')
    agentora_enable_memory_summaries: bool = Field(default=True, alias='AGENTORA_ENABLE_MEMORY_SUMMARIES')
    agentora_project_memory_boost: float = Field(default=1.2, alias='AGENTORA_PROJECT_MEMORY_BOOST')
    agentora_cross_project_memory_enabled: bool = Field(default=False, alias='AGENTORA_CROSS_PROJECT_MEMORY_ENABLED')
    agentora_global_memory_fallback_enabled: bool = Field(default=True, alias='AGENTORA_GLOBAL_MEMORY_FALLBACK_ENABLED')
    agentora_duplicate_suppression_enabled: bool = Field(default=True, alias='AGENTORA_DUPLICATE_SUPPRESSION_ENABLED')
    agentora_enable_team_debate: bool = Field(default=True, alias='AGENTORA_ENABLE_TEAM_DEBATE')
    agentora_default_team_mode: str = Field(default='careful', alias='AGENTORA_DEFAULT_TEAM_MODE')
    agentora_max_team_turns: int = Field(default=6, alias='AGENTORA_MAX_TEAM_TURNS')
    agentora_max_handoffs: int = Field(default=8, alias='AGENTORA_MAX_HANDOFFS')
    agentora_enable_single_agent_fallback: bool = Field(default=True, alias='AGENTORA_ENABLE_SINGLE_AGENT_FALLBACK')
    agentora_force_synthesis_on_budget_exhaust: bool = Field(default=True, alias='AGENTORA_FORCE_SYNTHESIS_ON_BUDGET_EXHAUST')
    agentora_enable_desktop_actions: bool = Field(default=True, alias='AGENTORA_ENABLE_DESKTOP_ACTIONS')
    agentora_enable_browser_actions: bool = Field(default=True, alias='AGENTORA_ENABLE_BROWSER_ACTIONS')
    agentora_action_require_approval_default: str = Field(default='ask_once', alias='AGENTORA_ACTION_REQUIRE_APPROVAL_DEFAULT')
    agentora_allowed_path_roots: str = Field(default='.', alias='AGENTORA_ALLOWED_PATH_ROOTS')
    agentora_blocked_path_roots: str = Field(default='', alias='AGENTORA_BLOCKED_PATH_ROOTS')
    agentora_allowed_domains: str = Field(default='localhost,127.0.0.1', alias='AGENTORA_ALLOWED_DOMAINS')
    agentora_blocked_domains: str = Field(default='', alias='AGENTORA_BLOCKED_DOMAINS')
    agentora_allowed_apps: str = Field(default='', alias='AGENTORA_ALLOWED_APPS')
    agentora_max_action_steps: int = Field(default=12, alias='AGENTORA_MAX_ACTION_STEPS')
    agentora_max_workflow_duration_seconds: int = Field(default=300, alias='AGENTORA_MAX_WORKFLOW_DURATION_SECONDS')

    coevo_url: str = Field(default='', alias='COEVO_URL')
    coevo_api_key: str = Field(default='', alias='COEVO_API_KEY')


    @property
    def allowed_tool_names(self) -> set[str]:
        return {x.strip() for x in self.agentora_allowed_tool_names.split(',') if x.strip()}

    @property
    def blocked_tool_names(self) -> set[str]:
        return {x.strip() for x in self.agentora_blocked_tool_names.split(',') if x.strip()}

    @property
    def http_allowlist(self) -> list[str]:
        return [x.strip() for x in self.agentora_http_allowlist.split(',') if x.strip()]

    @property
    def allowed_hosts(self) -> list[str]:
        return [h.strip() for h in self.agentora_allowed_hosts.split(',') if h.strip()]

    @property
    def memory_layer_weights(self) -> dict[str, float]:
        try:
            raw = json.loads(self.agentora_memory_layer_weights or '{}')
            return {str(k): float(v) for k, v in raw.items()}
        except Exception:
            return {}

    @property
    def context_layer_budgets(self) -> dict[str, int]:
        try:
            raw = json.loads(self.agentora_context_layer_budgets or '{}')
            return {str(k): int(v) for k, v in raw.items()}
        except Exception:
            return {}

    @property
    def allowed_path_roots(self) -> list[str]:
        return [x.strip() for x in self.agentora_allowed_path_roots.split(',') if x.strip()]

    @property
    def blocked_path_roots(self) -> list[str]:
        return [x.strip() for x in self.agentora_blocked_path_roots.split(',') if x.strip()]

    @property
    def allowed_domains(self) -> list[str]:
        return [x.strip() for x in self.agentora_allowed_domains.split(',') if x.strip()]

    @property
    def blocked_domains(self) -> list[str]:
        return [x.strip() for x in self.agentora_blocked_domains.split(',') if x.strip()]

    @property
    def allowed_apps(self) -> list[str]:
        return [x.strip() for x in self.agentora_allowed_apps.split(',') if x.strip()]


settings = Settings()
