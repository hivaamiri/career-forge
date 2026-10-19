"""Configuration loader and Pydantic schema validation for Job Pulse."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field


class TelegramConfig(BaseModel):
    bot_token: str = Field(..., description="Telegram Bot API token")
    chat_id: str = Field(..., description="Telegram recipient chat or channel ID")


class EmailConfig(BaseModel):
    enabled: bool = True
    imap_server: str = "imap.gmail.com"
    imap_port: int = 993
    username: str = ""
    password: str = ""
    check_interval_seconds: int = 300
    folder: str = "INBOX"


class ArbeitsagenturConfig(BaseModel):
    enabled: bool = True
    keywords: List[str] = Field(
        default_factory=lambda: [
            "backend engineer",
            "software engineer",
            "systems engineer",
            "devops",
            "cloud engineer",
            "platform engineer",
            "linux",
        ]
    )
    locations: List[str] = Field(
        default_factory=lambda: ["Berlin", "München", "Frankfurt", "Hamburg", "Remote"]
    )
    radius_km: int = 50
    poll_interval_seconds: int = 3600


class ATSConfig(BaseModel):
    enabled: bool = True
    personio_companies: List[str] = Field(default_factory=list)
    poll_interval_seconds: int = 3600


class MatcherConfig(BaseModel):
    inclusion_patterns: List[str] = Field(
        default_factory=lambda: [
            r"(?i)\b(backend|software\s*engineer|systems\s*engineer|network|devops|cloud|infrastructure|linux|platform)\b"
        ]
    )
    exclusion_patterns: List[str] = Field(
        default_factory=lambda: [
            r"(?i)\b(intern|praktikant|working\s*student|werkstudent|trainee|sales|marketing|frontend\s*only)\b"
        ]
    )
    locations: List[str] = Field(
        default_factory=lambda: [
            "Germany",
            "Deutschland",
            "Berlin",
            "Munich",
            "München",
            "Frankfurt",
            "Hamburg",
            "Remote",
        ]
    )


class DatabaseConfig(BaseModel):
    path: str = "data/jobs.sqlite"


class CareerOpsConfig(BaseModel):
    pipeline_path: str = "career-ops/data/pipeline.md"


class AppConfig(BaseModel):
    telegram: TelegramConfig
    email: EmailConfig = Field(default_factory=EmailConfig)
    arbeitsagentur: ArbeitsagenturConfig = Field(default_factory=ArbeitsagenturConfig)
    ats: ATSConfig = Field(default_factory=ATSConfig)
    matcher: MatcherConfig = Field(default_factory=MatcherConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    career_ops: CareerOpsConfig = Field(default_factory=CareerOpsConfig)


def find_default_config_path() -> Path:
    """Resolve the default config file path."""
    env_path = os.getenv("JOB_PULSE_CONFIG")
    if env_path:
        return Path(env_path)

    # Standard locations relative to project root
    candidate = Path("config/config.yaml")
    if candidate.exists():
        return candidate

    return candidate


def load_config(config_path: Optional[str | Path] = None) -> AppConfig:
    """Load and validate application configuration from a YAML file.

    Environment variables can override critical secrets:
    - TELEGRAM_BOT_TOKEN
    - TELEGRAM_CHAT_ID
    - IMAP_USERNAME
    - IMAP_PASSWORD
    """
    path = Path(config_path) if config_path else find_default_config_path()

    raw_data: dict = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                raw_data = loaded
    else:
        # If config file does not exist, check if minimum required settings exist in env
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not (bot_token and chat_id):
            raise FileNotFoundError(
                f"Config file not found at '{path}'. "
                f"Please copy 'config/config.example.yaml' to '{path}' and configure credentials, "
                f"or set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables."
            )

    # Allow environment variable overrides for sensitive fields
    if "telegram" not in raw_data:
        raw_data["telegram"] = {}
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        raw_data["telegram"]["bot_token"] = os.environ["TELEGRAM_BOT_TOKEN"]
    if os.getenv("TELEGRAM_CHAT_ID"):
        raw_data["telegram"]["chat_id"] = os.environ["TELEGRAM_CHAT_ID"]

    if "email" not in raw_data:
        raw_data["email"] = {}
    if os.getenv("IMAP_USERNAME"):
        raw_data["email"]["username"] = os.environ["IMAP_USERNAME"]
    if os.getenv("IMAP_PASSWORD"):
        raw_data["email"]["password"] = os.environ["IMAP_PASSWORD"]

    return AppConfig.model_validate(raw_data)
