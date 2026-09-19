"""Routes under /api/. Trailing slashes are optional so a missing "/" never 301s a POST."""

from django.urls import re_path

from trips import views

app_name = "trips"

urlpatterns = [
    re_path(r"^trips/plan/?$", views.PlanTripView.as_view(), name="plan"),
    re_path(r"^geocode/?$", views.GeocodeView.as_view(), name="geocode"),
    re_path(r"^reverse/?$", views.ReverseGeocodeView.as_view(), name="reverse"),
    re_path(r"^health/?$", views.HealthView.as_view(), name="health"),
]
