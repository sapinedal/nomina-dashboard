"""Sprint 1 — DEF-0002 OpenAPI exposure helpers."""


def test_openapi_hidden_by_default(monkeypatch):
    from app import main as main_mod

    monkeypatch.setattr(main_mod.settings, "EXPOSE_OPENAPI", False)
    assert main_mod._openapi_url() is None
    assert main_mod._docs_url() is None
    assert main_mod._redoc_url() is None


def test_openapi_only_with_explicit_flag(monkeypatch):
    from app import main as main_mod

    monkeypatch.setattr(main_mod.settings, "DEBUG", True)
    monkeypatch.setattr(main_mod.settings, "EXPOSE_OPENAPI", False)
    assert main_mod._openapi_url() is None

    monkeypatch.setattr(main_mod.settings, "EXPOSE_OPENAPI", True)
    assert main_mod._openapi_url() == "/api/openapi.json"
    assert main_mod._docs_url() == "/api/docs"
