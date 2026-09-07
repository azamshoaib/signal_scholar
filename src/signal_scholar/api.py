"""Django Ninja API layer for signal_scholar.

Establishes the typed API layer that future endpoints build on. Per
GitHub issue #4, this currently exposes only a health-check endpoint
to prove the wiring works end to end; real endpoints (topic search,
"similar but better", etc.) are added in later issues.
"""

from ninja import NinjaAPI

api = NinjaAPI()


@api.get("/health")
def health(request):
    return {"status": "ok"}
