"""Service-layer errors. Views translate them into the ``ApiError`` JSON shape."""

from __future__ import annotations


class ServiceError(Exception):
    """Base class: carries an ApiError ``code`` and the HTTP status to respond with."""

    code = "service_error"
    status = 500

    def __init__(self, message: str, *, details: dict[str, list[str]] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details


class GeocodeFailed(ServiceError):
    """A free-text location could not be resolved to coordinates."""

    code = "geocode_failed"
    status = 422


class RouteNotFound(ServiceError):
    """The router answered but found no drivable route between the waypoints."""

    code = "route_not_found"
    status = 422


class UpstreamUnavailable(ServiceError):
    """Every upstream host failed (timeout, 5xx, rate limit, malformed response)."""

    code = "upstream_unavailable"
    status = 502
