#!/usr/bin/env python3
"""NOAA SWPC OVATION aurora forecast capability."""

import requests

CAPABILITY = "aurora"

REQUEST_SCHEMA = {
    "latitude": "optional latitude from -90 to 90",
    "longitude": "optional longitude from -180 to 180; provide with latitude",
}

DESCRIPTION = (
    "Provides the latest NOAA Space Weather Prediction Center aurora "
    "forecast from the OVATION model. Returns forecast times, auroral "
    "activity statistics, and the strongest forecast locations. Optionally "
    "accepts latitude and longitude to report the nearest forecast point."
)
API_URL = "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json"


def _coordinate(value, minimum, maximum, name):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid {name}: {value}")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _distance_squared(latitude, longitude, point_latitude, point_longitude):
    lat_delta = latitude - point_latitude
    lon_delta = abs(longitude - point_longitude)
    lon_delta = min(lon_delta, 360.0 - lon_delta)
    return lat_delta * lat_delta + lon_delta * lon_delta


def _analyze_points(coordinates):
    points = []
    for point in coordinates:
        if not isinstance(point, list) or len(point) < 3:
            continue
        try:
            longitude = float(point[0])
            latitude = float(point[1])
            intensity = float(point[2])
        except (TypeError, ValueError):
            continue
        points.append({"latitude": latitude, "longitude": longitude, "intensity": intensity})

    if not points:
        return None

    active = [p for p in points if p["intensity"] > 0]
    strong = [p for p in points if p["intensity"] >= 50]
    strongest = max(points, key=lambda p: p["intensity"])
    northern = [p for p in points if p["latitude"] >= 0]
    southern = [p for p in points if p["latitude"] < 0]

    result = {
        "maximum_intensity": strongest["intensity"],
        "strongest_point": strongest,
        "active_grid_points": len(active),
        "strong_grid_points": len(strong),
    }
    if northern:
        result["northern_hemisphere"] = max(northern, key=lambda p: p["intensity"])
    if southern:
        result["southern_hemisphere"] = max(southern, key=lambda p: p["intensity"])
    return result


def _nearest_point(coordinates, latitude, longitude):
    best = None
    best_distance = None
    for point in coordinates:
        if not isinstance(point, list) or len(point) < 3:
            continue
        try:
            point_longitude = float(point[0])
            point_latitude = float(point[1])
            intensity = float(point[2])
        except (TypeError, ValueError):
            continue
        distance = _distance_squared(latitude, longitude, point_latitude, point_longitude)
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best = {"latitude": point_latitude, "longitude": point_longitude, "intensity": intensity}
    return best


def run_lookup(request):
    latitude = request.get("latitude")
    longitude = request.get("longitude")
    if latitude is not None:
        latitude = _coordinate(latitude, -90, 90, "latitude")
    if longitude is not None:
        longitude = _coordinate(longitude, -180, 180, "longitude")
    if (latitude is None) != (longitude is None):
        return {"error": "latitude and longitude must be supplied together."}

    try:
        response = requests.get(API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        return {"error": f"NOAA aurora service returned HTTP {status or 'error'}."}
    except requests.RequestException:
        return {"error": "NOAA aurora service request failed."}
    except ValueError:
        return {"error": "NOAA aurora service returned invalid JSON."}

    if not isinstance(data, dict):
        return {"error": "NOAA aurora service returned an unexpected response."}

    coordinates = data.get("coordinates", [])
    analysis = _analyze_points(coordinates)
    if analysis is None:
        return {"error": "NOAA aurora forecast contains no usable grid data."}

    result = {
        "source": "NOAA SWPC OVATION",
        "forecast_time": data.get("Observation Time"),
        "forecast_valid_time": data.get("Forecast Time"),
        "coordinates_count": len(coordinates),
        **analysis,
    }

    if latitude is not None and longitude is not None:
        result["requested_location"] = {"latitude": latitude, "longitude": longitude}
        result["nearest_forecast_point"] = _nearest_point(coordinates, latitude, longitude)

    return result


if __name__ == "__main__":
    import json
    print(json.dumps(run_lookup({}), indent=2))
