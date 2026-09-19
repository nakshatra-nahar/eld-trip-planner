"""Request validation (DRF serializers) for the trip-planner API.

Only input is validated here; responses are plain dicts shaped by
``frontend/src/types/api.ts`` and built in ``planner_service``.
"""

from __future__ import annotations

import math
from datetime import datetime

from rest_framework import serializers

START_TIME_FORMATS = ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S")
START_YEARS = (2000, 2100)  # far-off dates overflow the day arithmetic of multi-day plans
MAX_QUERY_LEN = 200


class FiniteFloatField(serializers.FloatField):
    """FloatField that rejects NaN/Infinity (JSON parsers may let them through) and booleans
    (which DRF would otherwise coerce to 1.0/0.0)."""

    def to_internal_value(self, data):
        if isinstance(data, bool):
            self.fail("invalid")
        value = super().to_internal_value(data)
        if not math.isfinite(value):
            self.fail("invalid")
        return value


class LocationInputSerializer(serializers.Serializer):
    label = serializers.CharField(required=False, allow_blank=True, max_length=MAX_QUERY_LEN, trim_whitespace=True)
    lat = FiniteFloatField(required=False, allow_null=True, min_value=-90, max_value=90)
    lon = FiniteFloatField(required=False, allow_null=True, min_value=-180, max_value=180)
    query = serializers.CharField(required=False, allow_blank=True, max_length=MAX_QUERY_LEN, trim_whitespace=True)

    def validate(self, attrs):
        has_lat, has_lon = attrs.get("lat") is not None, attrs.get("lon") is not None
        if has_lat != has_lon:
            raise serializers.ValidationError("Provide both lat and lon, or neither.")
        if not has_lat and not attrs.get("query"):
            raise serializers.ValidationError("Provide coordinates (lat/lon) or a non-empty query.")
        return attrs


class PlanOptionsSerializer(serializers.Serializer):
    include_inspections = serializers.BooleanField(required=False, default=True)
    rest_status = serializers.ChoiceField(choices=["SB", "OFF"], required=False, default="SB")
    fuel_stop_minutes = serializers.IntegerField(required=False, default=30, min_value=5, max_value=240)


class PlanRequestSerializer(serializers.Serializer):
    current_location = LocationInputSerializer()
    pickup_location = LocationInputSerializer()
    dropoff_location = LocationInputSerializer()
    current_cycle_used_hours = FiniteFloatField(min_value=0, max_value=70)
    start_time = serializers.CharField(max_length=25)
    options = PlanOptionsSerializer(required=False, allow_null=True)

    def validate_start_time(self, value: str) -> datetime:
        for fmt in START_TIME_FORMATS:
            try:
                parsed = datetime.strptime(value.strip(), fmt).replace(second=0)
            except ValueError:
                continue
            if not START_YEARS[0] <= parsed.year <= START_YEARS[1]:
                raise serializers.ValidationError(f"Start time must be between {START_YEARS[0]} and {START_YEARS[1]}.")
            return parsed
        raise serializers.ValidationError('Use the local time format "YYYY-MM-DDTHH:MM".')

    def validate(self, attrs):
        # Nested defaults only apply when "options" is sent; fill them in when it is not.
        if attrs.get("options") is None:
            options = PlanOptionsSerializer(data={})
            options.is_valid(raise_exception=True)
            attrs["options"] = dict(options.validated_data)
        return attrs


class GeocodeQuerySerializer(serializers.Serializer):
    q = serializers.CharField(min_length=2, max_length=MAX_QUERY_LEN, trim_whitespace=True)
    limit = serializers.IntegerField(required=False, default=6, min_value=1, max_value=10)


class ReverseQuerySerializer(serializers.Serializer):
    lat = FiniteFloatField(min_value=-90, max_value=90)
    lon = FiniteFloatField(min_value=-180, max_value=180)
