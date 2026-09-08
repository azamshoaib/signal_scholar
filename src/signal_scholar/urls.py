"""Root URL configuration for signal_scholar.

The placeholder `home` view stays in place to prove the project is
wired up correctly end to end. The Django Ninja API layer (see
`signal_scholar.api`) is mounted alongside it under `/api/`, per
GitHub issue #4. The Django admin site is mounted under `/admin/` per
GitHub issue #7.

Per GitHub issue #42, a public-facing login/logout flow is mounted at
`/login/` and `/logout/` using stock `django.contrib.auth` views (no
custom view logic) -- previously the only login path in the project was
`/admin/`'s own. This is a shared prerequisite for #25's follow/unfollow
endpoints and #27's personalized feed page, both of which need a
non-admin user able to authenticate as `request.user`.
"""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.http import HttpResponse
from django.urls import include, path

from signal_scholar.api import api


def home(request):
    return HttpResponse("SignalScholar is running.")


urlpatterns = [
    path("", home, name="home"),
    path("", include("papers.urls")),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("api/", api.urls),
    path("admin/", admin.site.urls),
]
