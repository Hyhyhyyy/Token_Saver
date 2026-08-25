from fastapi.testclient import TestClient

from skillforge.server import app


client = TestClient(app)


def test_cross_origin_write_is_rejected() -> None:
    response = client.post(
        "/api/simplify",
        json={"text": "safe synthetic input"},
        headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403


def test_same_origin_write_is_allowed() -> None:
    response = client.post(
        "/api/simplify",
        json={"text": "safe synthetic input"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200


def test_security_headers_are_present() -> None:
    response = client.get("/api/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_oversized_body_is_rejected_before_parsing() -> None:
    response = client.post(
        "/api/simplify",
        content=b"{}",
        headers={"Content-Length": "1048577"},
    )
    assert response.status_code == 413
