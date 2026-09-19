"""Per-client rate limiting for the public, unauthenticated API.

The API has no accounts, so abuse is bounded per client IP instead: planning and
autocomplete both fan out to free, fair-use upstream services (Valhalla, OSRM, Photon).
"""

from __future__ import annotations

from rest_framework.throttling import ScopedRateThrottle


class ClientScopedRateThrottle(ScopedRateThrottle):
    """``ScopedRateThrottle`` keyed on the real client IP.

    On Vercel, ``X-Vercel-Forwarded-For`` is set by the platform (clients cannot spoof it)
    and carries the visitor's IP even when the request arrives through the frontend's
    ``/api`` rewrite. Elsewhere (local dev, tests) DRF's default identification applies.
    """

    def get_ident(self, request) -> str:
        vercel_ip = request.META.get("HTTP_X_VERCEL_FORWARDED_FOR", "").split(",")[0].strip()
        return vercel_ip or super().get_ident(request)
