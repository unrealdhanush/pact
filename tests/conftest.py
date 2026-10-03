import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Tests never touch live ZooWork / Jev."""
    monkeypatch.setenv("PACT_MERCHANT", "local")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.setenv("PACT_TRANSPORT", "local")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)  # competitor checks use the committed cache
