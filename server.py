import asyncio
import logging
import math
import signal
import sys
from datetime import datetime
from typing import Literal, TypeVar
from zoneinfo import ZoneInfo

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ValidationError

from models import (
    ForecastResponse,
    FourDayOutlookResponse,
    OutlookDayForecast,
    PM25Response,
    PSIResponse,
    RainfallResponse,
    RainfallStation,
    TwentyFourHrForecastResponse,
    TwentyFourHrPeriod,
    UVResponse,
)

SGT = ZoneInfo("Asia/Singapore")
Verdict = Literal["GO", "CAUTION", "SKIP"]

mcp = FastMCP("sg-life")
BASE = "https://api-open.data.gov.sg/v2/real-time/api"
USER_AGENT = "sg-life-mcp/1.0"

# Approximate centre coordinates for known neighbourhoods (lat, lon).
# Used to find the nearest rainfall stations.
AREA_COORDS: dict[str, tuple[float, float]] = {
    # east
    "bedok":      (1.3236, 103.9273),
    "tampines":   (1.3496, 103.9568),
    "pasir ris":  (1.3721, 103.9491),
    "changi":     (1.3644, 103.9915),
    "simei":      (1.3400, 103.9530),
    "kembangan":  (1.3204, 103.9120),
    # west
    "jurong":     (1.3329, 103.7436),
    "clementi":   (1.3152, 103.7649),
    "buona vista":(1.3068, 103.7903),
    "boon lay":   (1.3388, 103.7069),
    "pioneer":    (1.3378, 103.6970),
    "tuas":       (1.2966, 103.6389),
    # north
    "woodlands":  (1.4382, 103.7890),
    "yishun":     (1.4230, 103.8350),
    "sembawang":  (1.4491, 103.8185),
    "admiralty":  (1.4404, 103.8008),
    "canberra":   (1.4432, 103.8301),
    # central .
    "bishan":     (1.3520, 103.8480),
    "toa payoh":  (1.3340, 103.8470),
    "ang mo kio": (1.3691, 103.8454),
    "novena":     (1.3200, 103.8438),
    "orchard":    (1.3048, 103.8318),
    "city":       (1.2830, 103.8515),
    "raffles":    (1.2890, 103.8536),
    "marina":     (1.2800, 103.8654),
    # south
    "queenstown": (1.2942, 103.7861),
    "bukit merah":(1.2819, 103.8239),
    "telok blangah": (1.2723, 103.8098),
    "harbourfront": (1.2654, 103.8217),
    "sentosa":    (1.2494, 103.8303),
}

# town to region mapping table
AREA_TO_REGION = {
    # east
    "bedok": "east", "tampines": "east", "pasir ris": "east",
    "changi": "east", "simei": "east", "kembangan": "east",
    # west
    "jurong": "west", "clementi": "west", "buona vista": "west",
    "boon lay": "west", "pioneer": "west", "tuas": "west",
    # north
    "woodlands": "north", "yishun": "north", "sembawang": "north",
    "admiralty": "north", "canberra": "north",
    # central
    "bishan": "central", "toa payoh": "central", "ang mo kio": "central",
    "novena": "central", "orchard": "central", "city": "central",
    "raffles": "central", "marina": "central",
    # south
    "queenstown": "south", "bukit merah": "south", "telok blangah": "south",
    "harbourfront": "south", "sentosa": "south",
}

_T = TypeVar("_T", bound=BaseModel)

async def fetch(endpoint: str, model: type[_T]) -> _T | None:
    """Fetch a data.gov.sg real-time endpoint. Returns a validated model or None."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{BASE}/{endpoint}", headers=headers, timeout=10.0
            )
            response.raise_for_status()
            return model.model_validate(response.json())
        except (httpx.HTTPError, ValidationError):
            return None

def area_to_region(area: str) -> str:
    """Map a neighbourhood name to one of the 5 PSI regions."""
    area_lower = area.lower()
    for key, region in AREA_TO_REGION.items():
        if key in area_lower:
            return region
    return "national"  # fallback: use national average

def area_to_coords(area: str) -> tuple[float, float]:
    """Return (lat, lon) for a neighbourhood, falling back to Singapore's centroid."""
    area_lower = area.lower()
    for key, coords in AREA_COORDS.items():
        if key in area_lower:
            return coords
    return (1.3521, 103.8198)  # geographic centre of Singapore

def nearest_stations(
    stations: list[RainfallStation], lat: float, lon: float, n: int = 3
) -> list[str]:
    """Return IDs of the n closest stations to (lat, lon) by Euclidean distance."""
    def dist(s: RainfallStation) -> float:
        return math.hypot(s.location.latitude - lat, s.location.longitude - lon)
    return [s.id for s in sorted(stations, key=dist)[:n]]

def find_area_forecast(forecast_raw: ForecastResponse, area: str) -> str | None:
    """Return the 2-hour forecast string for the named area, or None if not found."""
    area_lower = area.lower()
    try:
        for f in forecast_raw.data.items[0].forecasts:
            if area_lower in f.area.lower():
                return f.forecast
    except IndexError:
        pass
    return None

def merge_verdicts(*verdicts: Verdict) -> Verdict:
    if "SKIP" in verdicts:
        return "SKIP"
    if "CAUTION" in verdicts:
        return "CAUTION"
    return "GO"

def weather_verdict(text: str) -> tuple[Verdict, list[str]]:
    """Score a NEA forecast string for outdoor laundry (rain risk)."""
    forecast_lower = text.lower()
    issues: list[str] = []

    if any(
        w in forecast_lower
        for w in [
            "heavy thundery",
            "heavy rain",
            "thundery",
            "heavy showers",
            "moderate rain",
        ]
    ):
        issues.append(f"Weather: {text}")
        return "SKIP", issues

    if any(
        w in forecast_lower
        for w in ["showers", "light rain", "passing shower", "mist", "fog"]
    ):
        issues.append(f"Weather: {text}")
        return "CAUTION", issues

    return "GO", issues

def drying_verdict(humidity_high: int | float, wind_high: int | float) -> tuple[Verdict, list[str]]:
    """Score humidity and wind for how well laundry will dry."""
    issues: list[str] = []
    verdict: Verdict = "GO"

    if humidity_high >= 90:
        issues.append(f"Humidity up to {humidity_high:.0f}% — slow drying")
        verdict = "CAUTION"

    if wind_high >= 30:
        issues.append(f"Wind up to {wind_high:.0f} km/h — secure pegs")
        verdict = merge_verdicts(verdict, "CAUTION")

    return verdict, issues

def score_laundry_window(
    weather_text: str,
    *,
    humidity_high: int | float | None = None,
    wind_high: int | float | None = None,
    summary: str | None = None,
    raining: bool = False,
    rainfall_mm: float | None = None,
) -> tuple[Verdict, list[str]]:
    issues: list[str] = []
    verdicts: list[Verdict] = []

    if raining:
        mm = rainfall_mm if rainfall_mm is not None else 0
        issues.append(f"Rain detected: {mm:.1f} mm in past 5 min")
        verdicts.append("SKIP")

    weather_v, weather_issues = weather_verdict(weather_text)
    issues.extend(weather_issues)
    verdicts.append(weather_v)

    if summary:
        summary_v, summary_issues = weather_verdict(summary)
        if summary_v != "GO":
            for issue in summary_issues:
                if issue not in issues:
                    issues.append(f"Outlook: {summary}")
            verdicts.append(summary_v)

    if humidity_high is not None and wind_high is not None:
        dry_v, dry_issues = drying_verdict(humidity_high, wind_high)
        issues.extend(dry_issues)
        verdicts.append(dry_v)

    return merge_verdicts(*verdicts), issues

def find_current_24hr_period(
    forecast_raw: TwentyFourHrForecastResponse,
) -> TwentyFourHrPeriod | None:
    try:
        now = datetime.now(SGT)
        for period in forecast_raw.data.records[0].periods:
            start = period.time_period.start.astimezone(SGT)
            end = period.time_period.end.astimezone(SGT)
            if start <= now < end:
                return period
    except IndexError:
        pass
    return None

def region_forecast_text(period: TwentyFourHrPeriod, region: str) -> str | None:
    entry = period.regions.get(region)
    return entry.text if entry else None

def read_nearby_rainfall(
    rain_raw: RainfallResponse, area: str
) -> tuple[bool, float | None]:
    lat, lon = area_to_coords(area)
    nearby_ids = set(nearest_stations(rain_raw.data.stations, lat, lon, n=3))
    readings = rain_raw.data.readings[-1].data
    nearby_values = [r.value for r in readings if r.station_id in nearby_ids]
    if not nearby_values:
        return False, None
    max_mm = max(nearby_values)
    return any(v > 0 for v in nearby_values), max_mm

def outlook_day_label(day: OutlookDayForecast) -> str:
    return f"{day.day} {day.timestamp.strftime('%d %b')}"

def laundry_summary(verdict: Verdict) -> str:
    if verdict == "SKIP":
        return "Not a good time to hang laundry outside — expect rain or very slow drying."
    if verdict == "CAUTION":
        return "You can hang laundry outside, but rain or humidity may slow drying."
    return "Good conditions to hang laundry outside."

# tool
@mcp.tool()
async def should_i_jog_now(area: str = "Bedok") -> str:
    """
    Decide whether conditions are safe and comfortable for jogging right now
    in a Singapore neighbourhood.

    Combines 5 real-time signals from NEA/data.gov.sg:
    - PSI (air pollution — 24hr)
    - PM2.5 (fine particulate — 1hr)
    - UV index (solar radiation)
    - Rainfall (past 5 minutes at nearby stations)
    - 2-hour weather forecast

    Args:
        area: Singapore neighbourhood name, e.g. "Bedok", "Tampines",
              "Jurong West", "Woodlands", "Bishan". Defaults to Bedok.

    Returns a verdict (GO / CAUTION / SKIP), current conditions, and a
    plain-English reason so you know exactly why.
    """

    # fetch all signals
    psi_raw, pm25_raw, uv_raw, rain_raw, forecast_raw = await asyncio.gather(
            fetch("psi",             PSIResponse),
            fetch("pm25",            PM25Response),
            fetch("uv",        UVResponse),
            fetch("rainfall",        RainfallResponse),
            fetch("two-hr-forecast", ForecastResponse),
        )


    region = area_to_region(area)
    issues = []
    signals = {}

    # PSI
    psi = None
    if psi_raw:
        try:
            psi = psi_raw.data.items[0].readings.psi_twenty_four_hourly.get(region)
            signals["psi"] = psi
            if psi is not None:
                if psi > 200:
                    issues.append(f"PSI {psi} — very unhealthy air")
                if psi > 100:
                    issues.append(f"PSI {psi} — unhealthy air")
                elif psi > 55:
                    issues.append(f"PSI {psi} — moderate air quality")
        except IndexError:
            signals["psi"] = "unavailable"
    else:
        signals["psi"] = "unavailable"


    # PM2.5
    pm25 = None
    if pm25_raw:
        try:
            pm25 = pm25_raw.data.items[0].readings.pm25_one_hourly.get(region)
            signals["pm25"] = pm25
            if pm25 is not None and pm25 > 55:
                issues.append(f"PM2.5 {pm25} µg/m³ — elevated fine particles")
        except IndexError:
            signals["pm25"] = "unavailable"
    else:
        signals["pm25"] = "unavailable"

    # UV index
    uv = None
    if uv_raw:
        try:
            records = uv_raw.data.records
            if records:
                uv = records[-1].index[0].value
                signals["uv"] = uv
                if uv >= 11:
                    issues.append(f"UV index {uv} — extreme (wear sunscreen + hat)")
                elif uv >= 8:
                    issues.append(f"UV index {uv} — very high (protect skin)")
                elif uv >= 6:
                    issues.append(f"UV index {uv} — high (sunscreen needed)")
            else:
                signals["uv"] = "not available (outside 7am–7pm)"
        except IndexError:
            signals["uv"] = "unavailable"
    else:
        signals["uv"] = "unavailable"


    # rainfall
    raining = False
    if rain_raw:
        try:
            lat, lon = area_to_coords(area)
            nearby_ids = set(nearest_stations(rain_raw.data.stations, lat, lon, n=3))
            readings = rain_raw.data.readings[-1].data
            nearby_values = [r.value for r in readings if r.station_id in nearby_ids]
            wet = [v for v in nearby_values if v > 0]
            signals["rainfall_mm"] = max(nearby_values) if nearby_values else 0
            if wet:
                raining = True
                issues.append(
                    f"Rain near {area}: {max(wet):.1f} mm in past 5 min"
                )
        except IndexError:
            signals["rainfall_mm"] = "unavailable"
    else:
        signals["rainfall_mm"] = "unavailable"


    # 2hr weather forecast
    forecast = None
    if forecast_raw:
        forecast = find_area_forecast(forecast_raw, area)
        if forecast is None:
            forecast = "forecast area not found"
        signals["weather_forecast_2hr"] = forecast
        forecast_lower = (forecast or "").lower()
        if any(w in forecast_lower for w in ["heavy rain", "thundery", "showers"]):
            if not raining:  # avoid double-counting
                issues.append(f"Forecast: {forecast}")
    else:
        signals["weather_forecast_2hr"] = "unavailable"

    # ── verdict ─────────────────────────────────────────────────────────────────────────
    blockers = [i for i in issues if any(
        w in i for w in ["unhealthy", "PM2.5", "Rain detected", "Heavy", "Thundery"]
    )]
    warnings = [i for i in issues if i not in blockers]

    if blockers:
        verdict = "SKIP"
        summary = "Conditions are not suitable for jogging right now."
    elif warnings:
        verdict = "CAUTION"
        summary = "You can jog, but be aware of the conditions."
    else:
        verdict = "GO"
        summary = "Conditions look good for a jog!"

    logging.info("verdict=%s area=%s region=%s issues=%s", verdict, area, region, issues)

    # ── format output ───────────────────────────────────────────────────────────────────
    lines = [
        f"verdict: {verdict}",
        f"area: {area} (region: {region})",
        f"summary: {summary}",
        "",
        "signals:",
    ]
    for k, v in signals.items():
        lines.append(f"  {k}: {v}")

    if issues:
        lines.append("")
        lines.append("issues:")
        for issue in issues:
            prefix = "  BLOCK" if issue in blockers else "  WARN "
            lines.append(f"{prefix}  {issue}")

    return "\n".join(lines)


@mcp.tool()
async def hang_laundry_outside(area: str = "Bedok") -> str:
    """
    Decide whether it is a good time to hang laundry outside in a Singapore
    neighbourhood, and how the next few days look.

    Combines current and forecast signals from NEA/data.gov.sg:
    - Rainfall (past 5 minutes at nearby stations)
    - 2-hour area forecast
    - 24-hour regional forecast (today's time periods)
    - 4-day island-wide outlook (tomorrow onwards)

    Args:
        area: Singapore neighbourhood name, e.g. "Bedok", "Tampines",
              "Jurong West", "Woodlands", "Bishan". Defaults to Bedok.

    Returns a verdict (GO / CAUTION / SKIP) for right now, today's windows,
    and the next four days.
    """
    rain_raw, forecast_2hr_raw, forecast_24hr_raw, outlook_raw = await asyncio.gather(
        fetch("rainfall", RainfallResponse),
        fetch("two-hr-forecast", ForecastResponse),
        fetch("twenty-four-hr-forecast", TwentyFourHrForecastResponse),
        fetch("four-day-outlook", FourDayOutlookResponse),
    )

    region = area_to_region(area)
    now_issues: list[str] = []
    now_verdicts: list[Verdict] = []
    now_signals: dict[str, object] = {}

    raining = False
    rainfall_mm: float | None = None
    if rain_raw:
        try:
            raining, rainfall_mm = read_nearby_rainfall(rain_raw, area)
            now_signals["rainfall_mm"] = rainfall_mm if rainfall_mm is not None else 0
            if raining:
                now_issues.append(
                    f"Rain near {area}: {rainfall_mm:.1f} mm in past 5 min"
                )
                now_verdicts.append("SKIP")
        except IndexError:
            now_signals["rainfall_mm"] = "unavailable"
    else:
        now_signals["rainfall_mm"] = "unavailable"

    forecast_2hr = None
    if forecast_2hr_raw:
        forecast_2hr = find_area_forecast(forecast_2hr_raw, area)
        if forecast_2hr is None:
            forecast_2hr = "forecast area not found"
        now_signals["forecast_2hr"] = forecast_2hr
        v, issues = weather_verdict(forecast_2hr)
        now_verdicts.append(v)
        now_issues.extend(issues)
    else:
        now_signals["forecast_2hr"] = "unavailable"

    current_period = None
    current_period_text = None
    general_humidity_high: float | None = None
    general_wind_high: float | None = None
    if forecast_24hr_raw:
        try:
            record = forecast_24hr_raw.data.records[0]
            general = record.general
            general_humidity_high = general.relative_humidity.get("high")
            general_wind_high = general.wind["speed"]["high"]
            now_signals["forecast_24hr_general"] = general.forecast.text
            now_signals["humidity_pct"] = (
                f"{general.relative_humidity.get('low')}-{general_humidity_high}"
            )
            now_signals["wind_kmh"] = (
                f"{general.wind['speed']['low']}-{general_wind_high} "
                f"{general.wind['direction']}"
            )

            current_period = find_current_24hr_period(forecast_24hr_raw)
            if current_period:
                current_period_text = region_forecast_text(current_period, region)
                now_signals["forecast_24hr_period"] = (
                    f"{current_period.time_period.text}: {current_period_text}"
                )
                v, issues = score_laundry_window(
                    current_period_text or "unavailable",
                    humidity_high=general_humidity_high,
                    wind_high=general_wind_high,
                )
                now_verdicts.append(v)
                now_issues.extend(issues)
            else:
                now_signals["forecast_24hr_period"] = "unavailable"
        except (IndexError, KeyError, TypeError):
            now_signals["forecast_24hr_general"] = "unavailable"
    else:
        now_signals["forecast_24hr_general"] = "unavailable"

    if (
        general_humidity_high is not None
        and general_wind_high is not None
        and not current_period_text
    ):
        dry_v, dry_issues = drying_verdict(general_humidity_high, general_wind_high)
        now_verdicts.append(dry_v)
        now_issues.extend(dry_issues)

    verdict_now = merge_verdicts(*now_verdicts) if now_verdicts else "CAUTION"

    today_lines: list[str] = []
    if forecast_24hr_raw:
        try:
            for period in forecast_24hr_raw.data.records[0].periods:
                text = region_forecast_text(period, region) or "unavailable"
                v, _ = score_laundry_window(
                    text,
                    humidity_high=general_humidity_high,
                    wind_high=general_wind_high,
                )
                today_lines.append(
                    f"  {v:7}  {period.time_period.text}: {text}"
                )
        except IndexError:
            today_lines.append("  unavailable")

    outlook_lines: list[str] = []
    if outlook_raw:
        try:
            for day in outlook_raw.data.records[0].forecasts:
                humidity_high = day.relative_humidity["high"]
                wind_high = day.wind["speed"]["high"]
                v, _ = score_laundry_window(
                    day.forecast.text,
                    humidity_high=humidity_high,
                    wind_high=wind_high,
                    summary=day.forecast.summary,
                )
                summary = day.forecast.summary or day.forecast.text
                outlook_lines.append(
                    f"  {v:7}  {outlook_day_label(day)}: {day.forecast.text}"
                    f" — {summary}"
                )
        except IndexError:
            outlook_lines.append("  unavailable")
    else:
        outlook_lines.append("  unavailable")

    logging.info(
        "hang_laundry verdict_now=%s area=%s region=%s issues=%s",
        verdict_now,
        area,
        region,
        now_issues,
    )

    lines = [
        f"verdict_now: {verdict_now}",
        f"area: {area} (region: {region})",
        f"summary: {laundry_summary(verdict_now)}",
        "",
        "now:",
    ]
    for key, value in now_signals.items():
        lines.append(f"  {key}: {value}")

    if now_issues:
        lines.append("")
        lines.append("issues_now:")
        for issue in now_issues:
            prefix = "  BLOCK" if verdict_now == "SKIP" and "Rain" in issue else "  WARN "
            if any(w in issue for w in ["Thundery", "Heavy", "Weather: Heavy", "Rain detected"]):
                prefix = "  BLOCK"
            lines.append(f"{prefix}  {issue}")

    lines.extend(["", "today (24hr periods):"])
    lines.extend(today_lines or ["  unavailable"])

    lines.extend(["", "next_4_days:"])
    lines.extend(outlook_lines)

    return "\n".join(lines)


def main():
    logging.info("mcp server running...")

    # Make sure SIGINT/SIGTERM raise KeyboardInterrupt even while
    # the asyncio loop is parked on a stdin read.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    try:
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        logging.info("shutting down (ctrl+c)")
    except Exception as e:
        logging.exception("mcp server crashed: %s", e)
        sys.exit(1)

async def _test():
    """Run this directly to test without Claude Desktop."""
    tool = sys.argv[-1] if sys.argv[-1] in {"jog", "laundry"} else "jog"
    if tool == "laundry":
        result = await hang_laundry_outside("Bedok")
    else:
        result = await should_i_jog_now("Bedok")
    print(result)

if __name__ == "__main__":
    if "--test" in sys.argv:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")
        asyncio.run(_test())
    else:
        main()
