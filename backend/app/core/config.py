"""Typed application settings, loaded from environment variables / ``.env``."""

from __future__ import annotations

import re
from datetime import time
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.clock import ALLOWED_SIM_SPEEDS

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
DEFAULT_MOCK_SECRET = "dev-only-change-me"
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- app ---
    app_name: str = "CampusRide"
    app_env: Literal["dev", "test", "prod"] = "dev"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://localhost:5174"
    campus_timezone: str = "Asia/Kolkata"

    # --- database ---
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "campusride"
    telemetry_ttl_days: int = 30

    # --- auth ---
    auth_mode: Literal["mock", "firebase"] = "mock"
    mock_token_secret: str = DEFAULT_MOCK_SECRET
    mock_token_ttl_s: int = 7 * 24 * 3600
    firebase_project_id: str = ""

    # --- clock / simulator ---
    clock_mode: Literal["sim", "real"] = "sim"
    seed: int = 42
    sim_enabled: bool = True
    sim_autostart: bool = True
    sim_start_date: str = "auto"
    sim_start_time: time = time(7, 15)
    sim_speed: int = 5
    sim_tick_s: float = 1.0
    sim_telemetry_interval_s: float = 5.0
    sim_gps_noise_sigma_m: float = 8.0
    sim_dropout_prob: float = 0.01

    # --- tracking thresholds ---
    stop_arrival_radius_m: float = 40.0
    stop_approaching_m: float = 1_000.0
    bus_stale_after_s: float = 45.0
    deviation_threshold_m: float = 150.0
    deviation_consecutive_pings: int = 3

    # --- paths ---
    seed_data_dir: Path = BACKEND_DIR / "data" / "seed"

    @field_validator("sim_speed")
    @classmethod
    def _speed_allowed(cls, v: int) -> int:
        if v not in ALLOWED_SIM_SPEEDS:
            raise ValueError(f"SIM_SPEED must be one of {ALLOWED_SIM_SPEEDS}")
        return v

    @field_validator("sim_start_date")
    @classmethod
    def _start_date_format(cls, v: str) -> str:
        v = v.strip().lower()
        if v != "auto" and not _ISO_DATE.match(v):
            raise ValueError("SIM_START_DATE must be 'auto' or YYYY-MM-DD")
        return v

    @field_validator("campus_timezone")
    @classmethod
    def _tz_exists(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {v!r}") from exc
        return v

    @model_validator(mode="after")
    def _cross_checks(self) -> Settings:
        if self.auth_mode == "firebase" and not self.firebase_project_id:
            raise ValueError("AUTH_MODE=firebase requires FIREBASE_PROJECT_ID")
        if self.app_env == "prod" and self.auth_mode == "mock":
            raise ValueError("AUTH_MODE=mock is not allowed when APP_ENV=prod")
        return self

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.campus_timezone)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
