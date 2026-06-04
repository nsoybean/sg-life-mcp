from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ── Shared ────────────────────────────────────────────────────────────────────

class RegionValues(BaseModel):
    """One numeric value per NEA region."""
    north: float
    south: float
    east: float
    west: float
    central: float

    def get(self, region: str) -> float | None:  # type: ignore[override]
        return getattr(self, region, None)


# ── PSI ───────────────────────────────────────────────────────────────────────

class LabelLocation(BaseModel):
    latitude: float
    longitude: float


class RegionMetadata(_CamelModel):
    name: str
    label_location: LabelLocation


class PSIReadings(BaseModel):
    psi_twenty_four_hourly: RegionValues
    pm25_twenty_four_hourly: RegionValues
    pm25_sub_index: RegionValues
    pm10_twenty_four_hourly: RegionValues
    pm10_sub_index: RegionValues
    o3_eight_hour_max: RegionValues
    o3_sub_index: RegionValues
    no2_one_hour_max: RegionValues
    so2_twenty_four_hourly: RegionValues
    so2_sub_index: RegionValues
    co_eight_hour_max: RegionValues
    co_sub_index: RegionValues


class PSIItem(_CamelModel):
    date: date
    timestamp: datetime
    updated_timestamp: datetime
    readings: PSIReadings


class PSIData(_CamelModel):
    region_metadata: list[RegionMetadata]
    items: list[PSIItem]


class PSIResponse(_CamelModel):
    code: int
    data: PSIData
    error_msg: str | None


# ── PM2.5 ─────────────────────────────────────────────────────────────────────

class PM25Readings(BaseModel):
    pm25_one_hourly: RegionValues


class PM25Item(_CamelModel):
    date: date
    timestamp: datetime
    updated_timestamp: datetime
    readings: PM25Readings


class PM25Data(_CamelModel):
    region_metadata: list[RegionMetadata]
    items: list[PM25Item]


class PM25Response(_CamelModel):
    code: int
    data: PM25Data
    error_msg: str | None


# ── UV Index ──────────────────────────────────────────────────────────────────

class UVIndexEntry(_CamelModel):
    hour: datetime
    value: float


class UVRecord(_CamelModel):
    index: list[UVIndexEntry]
    date: datetime
    updated_timestamp: datetime
    timestamp: datetime


class UVData(_CamelModel):
    records: list[UVRecord]
    pagination_token: str | None = None


class UVResponse(_CamelModel):
    code: int
    data: UVData
    error_msg: str | None


# ── Rainfall ──────────────────────────────────────────────────────────────────

class RainfallStation(_CamelModel):
    id: str
    device_id: str
    name: str
    location: LabelLocation  # API uses "location", not "labelLocation"


class RainfallReading(BaseModel):
    station_id: str = Field(alias="stationId")
    value: float


class RainfallItem(_CamelModel):
    timestamp: datetime
    data: list[RainfallReading]


class RainfallData(_CamelModel):
    stations: list[RainfallStation]
    readings: list[RainfallItem]
    reading_type: str
    reading_unit: str
    pagination_token: str | None = None


class RainfallResponse(_CamelModel):
    code: int
    data: RainfallData
    error_msg: str | None


# ── 2-Hour Forecast ───────────────────────────────────────────────────────────

class ForecastArea(_CamelModel):
    name: str
    forecast: str
    label_location: LabelLocation


class ForecastItem(_CamelModel):
    update_timestamp: datetime
    timestamp: datetime
    valid_period: dict              # {start, end} ISO strings
    forecasts: list[ForecastArea]


class ForecastData(BaseModel):
    items: list[ForecastItem]


class ForecastResponse(_CamelModel):
    code: int
    data: ForecastData
    error_msg: str | None
