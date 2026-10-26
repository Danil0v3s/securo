"""White label branding exposed by GET /api/info (issue #1045)."""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


@pytest.fixture
def _clean_brand_env(monkeypatch):
    monkeypatch.delenv("APP_NAME", raising=False)
    monkeypatch.delenv("BRAND_LOGO_URL", raising=False)
    monkeypatch.delenv("BRAND_FAVICON_URL", raising=False)


async def test_app_info_branding_defaults_to_unset(
    client: AsyncClient, _clean_brand_env
):
    """Nothing configured: all fields come back null, so the frontend
    falls back to its built-in name and mark."""
    r = await client.get("/api/info")
    assert r.status_code == 200
    branding = r.json()["branding"]
    assert branding == {
        "name": None,
        "logo_url": None,
        "favicon_url": None,
    }


async def test_app_info_branding_reflects_instance_config(
    client: AsyncClient, _clean_brand_env, monkeypatch
):
    """APP_NAME and the BRAND_* URLs are surfaced for the frontend."""
    monkeypatch.setenv("APP_NAME", "Household Ledger")
    monkeypatch.setenv("BRAND_LOGO_URL", "/branding/logo.png")
    monkeypatch.setenv("BRAND_FAVICON_URL", "/branding/favicon.png")
    r = await client.get("/api/info")
    assert r.status_code == 200
    branding = r.json()["branding"]
    assert branding["name"] == "Household Ledger"
    assert branding["logo_url"] == "/branding/logo.png"
    assert branding["favicon_url"] == "/branding/favicon.png"
