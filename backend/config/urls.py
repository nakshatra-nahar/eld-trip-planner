"""Root URLconf: the whole app is a JSON API under /api/."""

from django.urls import include, path

urlpatterns = [
    path("api/", include("trips.urls")),
]

handler404 = "trips.views.not_found"
handler500 = "trips.views.server_error"
