from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, Field, field_validator

from app.models.common import Direction, Document


class TrafficIncident(BaseModel):
    """A temporary slowdown on part of a route (injected by scenarios)."""

    route_id: str
    direction: Direction | None = None
    """None = both directions."""
    from_m: float = Field(ge=0)
    to_m: float = Field(ge=0)
    start: AwareDatetime
    end: AwareDatetime
    factor: float = Field(gt=0, le=1)


class TrafficProfile(Document):
    """Time-of-day speed profile for one road class (``id`` = segment class).

    ``hourly_factor[h]`` is the multiplier on free-flow speed at hh:00 campus
    time; values in between are linearly interpolated, so the morning peak
    can be centred on 08:00 (≈0.55× free-flow) rather than spanning a whole hour.
    """

    free_flow_kmph: float = Field(gt=0)
    hourly_factor: list[float]
    incidents: list[TrafficIncident] = Field(default_factory=list)

    @field_validator("hourly_factor")
    @classmethod
    def _24_values(cls, v: list[float]) -> list[float]:
        if len(v) != 24:
            raise ValueError("hourly_factor needs exactly 24 values")
        if any(not 0 < f <= 1.5 for f in v):
            raise ValueError("hourly factors must be in (0, 1.5]")
        return v

    def factor_at(self, seconds_of_day: float) -> float:
        """Speed multiplier at a campus-local time of day (seconds since midnight)."""
        s = seconds_of_day % 86_400
        h = int(s // 3600)
        frac = (s - h * 3600) / 3600
        a, b = self.hourly_factor[h], self.hourly_factor[(h + 1) % 24]
        return a + (b - a) * frac

    @property
    def free_flow_mps(self) -> float:
        return self.free_flow_kmph / 3.6
