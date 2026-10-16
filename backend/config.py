from functools import lru_cache
import os
from pydantic_settings import BaseSettings

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_named_env(*names: str) -> str:
    for name in names:
        val = os.environ.get(name)
        if val and val.strip():
            return val.strip()
    wanted = {n.lower() for n in names}
    for k, v in os.environ.items():
        if k.lower() in wanted and v and v.strip():
            return v.strip()
    return ""


def _read_env_api_key() -> str:
    # 优先 DeepSeek（DP_Apikey），避免系统里残留的耗尽千问 Key 抢先命中
    return _read_named_env(
        "DP_Apikey",
        "DP_APIKEY",
        "DP_API_KEY",
        "DEEPSEEK_API_KEY",
        "Apikey",
        "APIKEY",
        "ApiKey",
        "API_KEY",
        "DASHSCOPE_API_KEY",
        "LLM_API_KEY",
    )


_MODEL_ALIASES = {
    "v4flash": "deepseek-flash",
    "v4-flash": "deepseek-flash",
    "deepseek-v4-flash": "deepseek-flash",
    "deepseek-v4.1-flash": "deepseek-flash",
    "flash": "deepseek-flash",
}


def _normalize_model(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return "deepseek-flash"
    return _MODEL_ALIASES.get(raw.lower(), raw)


class Settings(BaseSettings):
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-flash"
    vision_model: str = "deepseek-flash"
    mock_llm: bool = False

    # 留空时回退到 HuggingFace 在线模型；填写本地路径可离线加载
    bge_m3_model_path: str = ""
    use_local_bge: bool = False

    app_env: str = "local"
    log_level: str = "INFO"
    company_name: str = "海贸礼品中国分部"
    app_name: str = "海贸工作台"
    default_tenant_id: str = "tenant_demo"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # 允许跨域访问前端的来源，逗号分隔。默认仅放行本机开发端口。
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # 新增员工账号时的初始密码。管理员应在首次登录后要求本人修改。
    default_user_password: str = "123456"

    knowledge_dir: str = os.path.join(_PROJECT_ROOT, "data", "knowledge")
    seed_dir: str = os.path.join(_PROJECT_ROOT, "data", "seed")
    storage_dir: str = os.path.join(_PROJECT_ROOT, "storage")

    # Milvus（对齐 eduagent：dense + sparse hybrid）
    milvus_host: str = "127.0.0.1"
    milvus_port: int = 19530
    milvus_collection: str = "gift_knowledge"
    use_milvus: bool = True

    # Redis 对话缓存（凭据必须通过环境变量或 .env.local 提供）
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 2
    redis_ttl_seconds: int = 86400
    redis_key_prefix: str = "gift_chat"

    # MySQL FAQ（凭据必须通过环境变量或 .env.local 提供）
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3307
    mysql_user: str = "gift"
    mysql_password: str = ""
    mysql_database: str = "gift_desk"
    faq_bm25_confidence: float = 0.78
    faq_bm25_min_score: float = 5.0

    chat_rag_top_k: int = 4

    class Config:
        env_file = os.path.join(_PROJECT_ROOT, ".env.local")
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"

    @property
    def project_root(self) -> str:
        return _PROJECT_ROOT

    @property
    def resolved_api_key(self) -> str:
        return (self.llm_api_key or _read_env_api_key()).strip()

    @property
    def resolved_llm_model(self) -> str:
        return _normalize_model(self.llm_model)

    @property
    def resolved_vision_model(self) -> str:
        return _normalize_model(self.vision_model)

    @property
    def use_real_llm(self) -> bool:
        if self.mock_llm:
            return False
        return bool(self.resolved_api_key)

    @property
    def resolved_cors_origins(self) -> list[str]:
        origins = [o.strip() for o in (self.cors_origins or "").split(",") if o.strip()]
        return origins or ["http://localhost:5173"]


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
