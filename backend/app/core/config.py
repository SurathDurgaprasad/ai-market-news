from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import os


def _hydrate_os_environ(*names: str) -> None:
    """
    Copy User/Machine environment variables into os.environ when the process
    env is empty. IDE processes are often started before a newly set User
    variable is inherited. Never logs values.
    """
    if os.name != "nt":
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
    "LLM_PROVIDER",
    "NVIDIA_MODEL",
    "NVIDIA_BASE_URL",
    "TESTING",
    "TEST_MODE",
)


class Settings(BaseSettings):
    PROJECT_NAME: str = "AI World Intelligence Platform"
    
    # Environment
    TEST_MODE: bool = False
    
    # SQLite is the product database. Do not point this at PostgreSQL.
    DATABASE_URL: str = "sqlite:///./ai_platform.db"
    
    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Which production provider the factory may construct. Never inferred from
    # a leftover OpenAI key if nvidia is selected.
    LLM_PROVIDER: str = "nvidia"
    
    # LLM credentials — read from environment / .env only. Never log these.
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    GEMINI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-sonnet-4-5"
    NVIDIA_API_KEY: Optional[str] = None
    NVIDIA_MODEL: str = "openai/gpt-oss-20b"
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    def get_database_url(self) -> str:
        if self.TEST_MODE:
            return "sqlite:///./test.db"
        url = (self.DATABASE_URL or "").strip()
        if url.startswith("sqlite"):
            return url
        return "sqlite:///./ai_platform.db"

settings = Settings()
