"""HTTP API: trip planning, geocoding autocomplete, offline reverse geocoding, health.

Every error leaves as the ``ApiError`` JSON shape ``{"error", "code", "details?"}``:
DRF validation errors via ``api_exception_handler`` and service failures via the
``ServiceError`` hierarchy.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse
from rest_framework import exceptions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView, exception_handler

from trips import planner_service
from trips.serializers import GeocodeQuerySerializer, PlanRequestSerializer, ReverseQuerySerializer
from trips.services import geocoding
from trips.services.errors import ServiceError

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- errors


def error_body(message: str, code: str, details: dict[str, list[str]] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": message, "code": code}
    if details:
        body["details"] = details
    return body


def _flatten_details(detail: Any, prefix: str = "") -> dict[str, list[str]]:
    """DRF's nested error structure -> ``{"pickup_location.lat": ["..."]}``."""
    out: dict[str, list[str]] = {}
    if isinstance(detail, dict):
        for key, value in detail.items():
            name = prefix if key == "non_field_errors" and prefix else f"{prefix}.{key}" if prefix else str(key)
            for k, msgs in _flatten_details(value, name).items():
                out.setdefault(k, []).extend(msgs)
    elif isinstance(detail, list):
        if all(not isinstance(d, (dict, list)) for d in detail):
            out[prefix or "non_field_errors"] = [str(d) for d in detail]
        else:
            for i, item in enumerate(detail):
                for k, msgs in _flatten_details(item, f"{prefix}[{i}]").items():
                    out.setdefault(k, []).extend(msgs)
    else:
        out[prefix or "non_field_errors"] = [str(detail)]
    return out


def _summary(details: dict[str, list[str]]) -> str:
    field, messages = next(iter(details.items()))
    if field == "non_field_errors":
        return messages[0]
    return f"{field.replace('_', ' ')}: {messages[0]}"


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """DRF ``EXCEPTION_HANDLER``: render every error as an ``ApiError``."""
    if isinstance(exc, ServiceError):
        return Response(error_body(exc.message, exc.code, exc.details), status=exc.status)

    if isinstance(exc, exceptions.ValidationError):
        details = _flatten_details(exc.detail)
        return Response(error_body(_summary(details), "validation_error", details), status=status.HTTP_400_BAD_REQUEST)

    if isinstance(exc, exceptions.ParseError):
        return Response(error_body("Request body is not valid JSON.", "validation_error"), status=exc.status_code)

    if isinstance(exc, RequestDataTooBig):
        return Response(error_body("Request body is too large.", "payload_too_large"), status=413)
    if isinstance(exc, RecursionError):  # JSON nested too deeply to decode
        return Response(error_body("Request body is not valid JSON.", "validation_error"), status=400)

    if isinstance(exc, exceptions.Throttled):
        response = exception_handler(exc, context)  # sets the Retry-After header (whole seconds)
        retry_after = response.headers.get("Retry-After")
        wait = f" Try again in {retry_after} s." if retry_after else " Try again shortly."
        response.data = error_body(f"Too many requests from your network.{wait}", "rate_limited")
        return response

    response = exception_handler(exc, context)
    if response is not None:  # other APIExceptions (405, 415, 404, throttled, ...)
        detail = getattr(exc, "detail", None)
        message = str(detail) if isinstance(detail, str) else str(getattr(exc, "default_detail", "Request failed."))
        response.data = error_body(message, getattr(exc, "default_code", "error"))
        return response

    log.exception("Unhandled error in %s", context.get("view").__class__.__name__ if context.get("view") else "view")
    return Response(
        error_body("Something went wrong while planning this trip. Please try again.", "internal_error"),
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


# ---------------------------------------------------------------- views


class PlanTripView(APIView):
    """POST /api/trips/plan/  PlanRequest -> PlanResponse (rate-limited per client IP)."""

    throttle_scope = "plan"

    def post(self, request: Request) -> Response:
        serializer = PlanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        budget = float(getattr(settings, "PLAN_TIME_BUDGET_SECONDS", planner_service.DEFAULT_BUDGET_S))
        return Response(planner_service.plan_trip(serializer.validated_data, budget_s=budget))


class GeocodeView(APIView):
    """GET /api/geocode/?q=...  -> GeocodeResponse (US/CA only, cached, rate-limited per IP)."""

    throttle_scope = "geocode"

    def get(self, request: Request) -> Response:
        serializer = GeocodeQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        # Autocomplete: Photon only (Nominatim's usage policy forbids autocomplete).
        results = geocoding.geocode(
            serializer.validated_data["q"], limit=serializer.validated_data["limit"], allow_fallback=False
        )
        response = Response({"results": results})
        response["Cache-Control"] = "public, max-age=3600"
        return response


class ReverseGeocodeView(APIView):
    """GET /api/reverse/?lat=..&lon=..  -> ReverseGeocodeResponse (offline dataset)."""

    def get(self, request: Request) -> Response:
        serializer = ReverseQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response({"result": geocoding.reverse(data["lat"], data["lon"])})


class HealthView(APIView):
    """GET /api/health/  -> {"status": "ok"}."""

    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})


# ---------------------------------------------------------------- non-DRF fallbacks


def not_found(request, exception=None) -> JsonResponse:
    return JsonResponse(error_body("Not found.", "not_found"), status=404)


def server_error(request) -> JsonResponse:
    return JsonResponse(error_body("Internal server error.", "internal_error"), status=500)
