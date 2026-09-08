"""Django Ninja API layer for signal_scholar.

Establishes the typed API layer that future endpoints build on. Per
GitHub issue #4, this originally exposed only a health-check endpoint to
prove the wiring works end to end. Per #15, paper-related endpoints
(topic search, and later "similar but better" etc.) now live in the
`papers` app instead, to keep app-specific code out of this
project-level package -- this file keeps only the `NinjaAPI` instance
and the `/health` check, and mounts the `papers` router at an empty
prefix so its routes resolve at the same level as `/health` (e.g.
`@router.get("/search")` in `papers.api` becomes `/api/search`, not
`/api/papers/search`).
"""

from ninja import NinjaAPI

from papers.api import router as papers_router

api = NinjaAPI()


@api.get("/health")
def health(request):
    return {"status": "ok"}


api.add_router("", papers_router)
