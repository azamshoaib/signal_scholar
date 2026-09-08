"""Root URL configuration for signal_scholar.

The placeholder `home` view stays in place to prove the project is
wired up correctly end to end. The Django Ninja API layer (see
`signal_scholar.api`) is mounted alongside it under `/api/`, per
GitHub issue #4. The Django admin site is mounted under `/admin/` per
GitHub issue #7.
"""

from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path

from signal_scholar.api import api


def home(request):
    return HttpResponse("SignalScholar is running.")


urlpatterns = [
    path("", home, name="home"),
    path("", include("papers.urls")),
    path("api/", api.urls),
    path("admin/", admin.site.urls),
]
