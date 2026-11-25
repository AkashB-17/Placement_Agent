"""CORS: the Next.js origin may call the API with a bearer token; other origins may not."""
from fastapi.testclient import TestClient


def _preflight(client: TestClient, origin: str):
    return client.options(
        "/jds",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )


def test_frontend_origin_allowed(client: TestClient) -> None:
    response = _preflight(client, "http://localhost:3000")
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in response.headers


def test_every_method_the_api_uses_passes_preflight(client: TestClient) -> None:
    """A method missing from allow_methods fails in the browser as 'no response' (the
    preflight is refused), while the same call works from scripts. DELETE /jds/{id} hit this."""
    # The OpenAPI schema lists every path and method, however routers are nested.
    used = {method.upper() for path in client.app.openapi()["paths"].values() for method in path}
    assert {"GET", "POST", "PUT", "DELETE"} <= used
    for method in sorted(used):
        response = client.options(
            "/jds/some-id",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert response.status_code == 200, f"{method} preflight refused"
        assert method in response.headers["access-control-allow-methods"]


def test_unknown_origin_refused(client: TestClient) -> None:
    response = _preflight(client, "https://evil.example")
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_crash_returns_json_500_with_cors_header(client: TestClient, monkeypatch) -> None:
    """A crash must still reach the browser as a readable error, not a CORS failure."""

    def boom():
        raise RuntimeError("secret internals")

    monkeypatch.setattr("app.routers.jds.list_jds", boom)
    response = client.get("/jds", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "secret internals" not in response.text


def test_simple_request_from_frontend_gets_cors_header(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
