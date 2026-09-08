"""Root URL configuration for signal_scholar.

The Django Ninja API layer (see `signal_scholar.api`) is mounted under
`/api/`, per GitHub issue #4. The Django admin site is mounted under
`/admin/` per GitHub issue #7.

Per GitHub issue #42, a public-facing login/logout flow is mounted at
`/login/` and `/logout/` using stock `django.contrib.auth` views (no
custom view logic) -- previously the only login path in the project was
`/admin/`'s own. This is a shared prerequisite for #25's follow/unfollow
endpoints and #27's personalized feed page, both of which need a
non-admin user able to authenticate as `request.user`.

`home` used to be a bare "SignalScholar is running." placeholder text
response -- proof-of-life for #1, but a dead end with no way to reach
/search/ or /feed/ from it. It now renders a minimal landing page with
links to the pages that actually exist, since nothing else in the
original backlog ever built real site navigation.
"""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.shortcuts import render
from django.urls import include, path

from signal_scholar.api import api


def home(request):
    return render(request, "signal_scholar/home.html")


urlpatterns = [
    path("", home, name="home"),
    path("", include("papers.urls")),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("api/", api.urls),
    path("admin/", admin.site.urls),
]
