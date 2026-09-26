from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import os


def _hydrate_os_environ(*names: str) -> None:
    """
    Copy User/Machine environment variables into os.environ when the process
    env is empty. IDE processes are often started before a newly set User
    variable is inherited. Never logs values.

    LLM_CREDENTIALS_DISABLED=1 skips it: the test suite removes provider
    keys on purpose and they must not come back from the registry.
    """
    if os.name != "nt" or os.environ.get("LLM_CREDENTIALS_DISABLED") == "1":
        return
    try:
        import winreg
    except ImportError:
        return
    hives = (
        (winreg.HKEY_CURRENT_USER, r"Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    )
    for name in names:
        current = os.environ.get(name)
        if current and str(current).strip():
            continue
        for hive, path in hives:
            try:
                with winreg.OpenKey(hive, path) as key:
                    raw, _ = winreg.QueryValueEx(key, name)
            except OSError:
                continue
            if raw and str(raw).strip():
                os.environ[name] = str(raw)
                break


_hydrate_os_environ(
    "NVIDIA_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_REGION",
    "BEDROCK_MODEL_ID",
    "LLM_PROVIDER",
    "OPENAI_MODEL",
    "ANTHROPIC_MODEL",
    "NVIDIA_MODEL",
    "NVIDIA_BASE_URL",
    "TESTING",
    "TEST_MODE",
)


class Settings(BaseSettings):
    PROJECT_NAME: str = "AI Market News"
    
    # Environment
    TEST_MODE: bool = False
    
    # SQLite is the product database. Do not point this at PostgreSQL.
    DATABASE_URL: str = "sqlite:///./ai_platform.db"

    # Comma-separated list of allowed CORS origins. No wildcard by
    # default — see docs/security-findings.md CORS-01: allow_origins=["*"]
    # combined with allow_credentials=True was a known-bad combination.
    # Defaults to the frontend's local dev origins; override via env for
    # any other deployment target.
    CORS_ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Which production provider the factory may construct. Exactly one is
    # used; there is no fallback between providers. OpenAI is the live
    # default. NVIDIA, Anthropic and Bedrock stay selectable here. NVIDIA was
    # the development default until its latency (tens of seconds per call,
    # outages past the 330s deadline) stalled live ingestion.
    LLM_PROVIDER: str = "openai"
    
    # LLM credentials — read from environment / .env only. Never log these.
    OPENAI_API_KEY: Optional[str] = None
    # gpt-4.1-mini split same-incident coverage into separate cards (8/11 on
    # real merge pairs vs 11/11 for gpt-4.1); see validate_openai_live.py.
    OPENAI_MODEL: str = "gpt-4.1"
    GEMINI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-sonnet-4-5"
    NVIDIA_API_KEY: Optional[str] = None
    NVIDIA_MODEL: str = "openai/gpt-oss-20b"
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"

    # Amazon Bedrock. AWS credentials are intentionally optional here —
    # boto3's own default credential chain (env vars, ~/.aws/credentials,
    # an IAM role, SSO) is the normal way to authenticate; these fields
    # are only for explicitly overriding that chain. BEDROCK_MODEL_ID and
    # AWS_REGION have no sensible default and ARE required for
    # LLM_PROVIDER=bedrock — see provider_is_configured() /
    # get_llm_provider() in app/core/providers/llm.py.
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: Optional[str] = None
    BEDROCK_MODEL_ID: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    def get_database_url(self) -> str:
        if self.TEST_MODE:
            return "sqlite:///./test.db"
        url = (self.DATABASE_URL or "").strip()
        if url.startswith("sqlite"):
            return url
        return "sqlite:///./ai_platform.db"

    def get_cors_allowed_origins(self) -> list[str]:
        raw = self.CORS_ALLOWED_ORIGINS or ""
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

settings = Settings()
