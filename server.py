import logging
import signal
import sys
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("sg-life")
BASE = "https://api-open.data.gov.sg/v2/real-time/api"
USER_AGENT = "sg-life-mcp/1.0"

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

# fetch helper function
async def fetch(endpoint: str) -> dict[str, Any] | None:
    """Fetch a data.gov.sg real-time endpoint. Returns parsed JSON or None."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{BASE}/{endpoint}", headers=headers, timeout=10.0
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

def area_to_region(area: str) -> str:
    """Map a neighbourhood name to one of the 5 PSI regions."""
    area_lower = area.lower()
    for key, region in AREA_TO_REGION.items():
        if key in area_lower:
            return region
    return "national"  # fallback: use national average

# tool
@mcp.tool()
async def should_i_jog_now(area: str = "Bedok") -> str:
    # implement me
    return 'yup, weather is good! go out!'


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

if __name__ == "__main__":
    main()
