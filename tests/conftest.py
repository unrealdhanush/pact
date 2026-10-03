import pytest


@pytest.fixture(autouse=True)
def _no_live_services(monkeypatch):
    """Tests never touch live ZooWork / Jev."""
    monkeypatch.setenv("PACT_MERCHANT", "local")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    for k in ("BAND_SHOPPER_AGENT_KEY", "BAND_MERCHANT_AGENT_KEY", "BAND_API_KEY", "BAND_HUMAN_API_KEY"):
        monkeypatch.delenv(k, raising=False)  # tests never touch live BAND  # competitor checks use the committed cache
