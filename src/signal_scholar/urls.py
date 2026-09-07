"""Root URL configuration for signal_scholar.

Just a placeholder home view for now to prove the project is wired up
correctly end to end. The real API layer is added in a follow-up issue.
"""

from django.http import HttpResponse
from django.urls import path


def home(request):
    return HttpResponse("SignalScholar is running.")


urlpatterns = [
    path("", home, name="home"),
]
