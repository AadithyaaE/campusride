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

    # --- route deviation (Feature 10). Above synthetic GPS noise (σ 8 m/axis → < ~35 m). ---
    route_minor_deviation_m: float = 50.0
    """> this far from the planned route → MINOR_DEVIATION."""
    route_major_deviation_m: float = 150.0
    """≥ this far from the planned route → MAJOR_DEVIATION (alert)."""
    sim_driver_controlled_buses: str = "B07"
    """Feature 12: simulated buses (comma list) whose trips start/stop from the Driver App.
    They wait at their first stop until the driver presses Start Trip; every other bus
    keeps following the automatic demo schedule. Empty = all buses automatic."""
    sim_deviation_minor_offset_m: float = 100.0
    """Demo: perpendicular offset applied to simulated GPS in ``minor`` mode."""
    sim_deviation_major_offset_m: float = 300.0
    """Demo: perpendicular offset applied to simulated GPS in ``major`` mode."""

    # --- commute decision (Feature 7, prototype values — not statistically calibrated) ---
    walking_speed_mps: float = 1.4
    """Fallback walking speed when a student has no profile speed (seeded profiles carry one)."""
    commute_safety_buffer_s: float = 120.0
    """Arrive at least this long before the bus (road crossing, finding the boarding point)."""
    recovery_delay_threshold_s: float = 300.0
    """Feature 9: an assigned bus this late (s behind the timetable) triggers recovery options."""
    recovery_max_alternatives: int = 3
    # --- in-app alerts (Feature 11). Delay reuses tracking's DELAYED_AFTER_S rule. ---
    alert_approaching_window_minutes: float = 5.0
    """BUS_APPROACHING when the assigned bus's ETA to the boarding stop is within this window."""
    alert_capacity_warning_percent: int = 80
    """CAPACITY_WARNING when occupancy reaches this percentage of capacity."""
    alert_evaluation_interval_s: float = 15.0
    """Student alert sweep cadence in SIMULATION seconds (approaching / missed / alternative)."""
    alert_evaluation_min_wall_s: float = 5.0
    """…but never more often than this in wall-clock seconds (keeps 20× demos light)."""
    alert_student_route_deviation: bool = True
    """Also notify the assigned students when their bus enters a major route deviation."""
    """Feature 9: other recovery options listed after the recommended one."""
    # --- real-time WebSocket push (Feature 14). Wall-clock seconds. ---
    ws_auth_timeout_s: float = 10.0
    """A new socket must authenticate (first message) within this time."""
    ws_heartbeat_s: float = 20.0
    """Server → client ``ping`` interval; clients answer ``pong``."""
    ws_idle_timeout_s: float = 60.0
    """Close a socket that sent nothing (not even ``pong``) for this long."""
    ws_flush_interval_s: float = 1.0
    """Bus updates are coalesced per bus and pushed at most once per interval."""
    ws_overview_min_interval_s: float = 2.0
    """Admin KPI overview push: at most once per interval, only after something changed."""
    ws_queue_size: int = 500
    """Per-connection send queue; a client that falls this far behind is disconnected."""
    student_location_mode: Literal["synthetic", "off"] = "synthetic"
    """``synthetic``: deterministic demo location near the boarding stop (no real GPS yet);
    ``off``: no location source → LOCATION_UNAVAILABLE."""

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
        if not 0 < self.route_minor_deviation_m < self.route_major_deviation_m:
            raise ValueError("need 0 < ROUTE_MINOR_DEVIATION_M < ROUTE_MAJOR_DEVIATION_M")
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
