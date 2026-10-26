"""Environment-driven capability flags.

One parser, so everything that asks "is this capability enabled on this
deployment?" gets the same answer: the `/api/info` payload the frontend
reads, and the module resolver's deployment layer.
"""
import os

TRUTHY = ("1", "true", "yes", "on")


def feature_flag(name: str, default: str = "false") -> bool:
    """Read a boolean capability flag from the environment."""
    return os.getenv(name, default).strip().lower() in TRUTHY


def branding() -> dict:
    """White label brand for /api/info. Null means the deployment left it unset."""
    name = os.getenv("APP_NAME", "").strip()
    logo = os.getenv("BRAND_LOGO_URL", "").strip()
    favicon = os.getenv("BRAND_FAVICON_URL", "").strip()
    return {
        "name": name or None,
        "logo_url": logo or None,
        "favicon_url": favicon or None,
    }
