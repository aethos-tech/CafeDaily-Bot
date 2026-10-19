"""Container readiness: authenticated API connection (Discord may await panel setup)."""
import os
import sys
import urllib.request


def main() -> int:
    url = os.environ.get("HUB_API_URL", "").rstrip("/") + "/api/daily-discord/bridge/bootstrap"
    request = urllib.request.Request(url, headers={"User-Agent": "KinaCafeDaily/1.0", "Authorization": "Bearer " + os.environ.get("HUB_BRIDGE_KEY", "")})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return 0 if response.status == 200 else 1
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())
