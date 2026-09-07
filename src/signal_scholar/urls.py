"""Root URL configuration for signal_scholar.

The placeholder `home` view stays in place to prove the project is
wired up correctly end to end. The Django Ninja API layer (see
`signal_scholar.api`) is mounted alongside it under `/api/`, per
GitHub issue #4.
"""

from django.http import HttpResponse
from django.urls import path

from signal_scholar.api import api


def home(request):
    return HttpResponse("SignalScholar is running.")


urlpatterns = [
    path("", home, name="home"),
    path("api/", api.urls),
]
