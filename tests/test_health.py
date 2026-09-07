"""Proof-of-life test for the Django Ninja API layer.

Per GitHub issue #4, this proves the `/api/` mount and its health-check
endpoint work end to end, without touching a database.
"""


def test_health_endpoint_returns_ok(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
