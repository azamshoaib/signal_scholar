"""Proof-of-life test: the Django project is wired up and responds.

Per GitHub issue #1, this is the single scaffolding test that proves the
environment is configured correctly before real feature work starts.
"""


def test_home_page_returns_200(client):
    response = client.get("/")
    assert response.status_code == 200
