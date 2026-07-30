import math

EARTH_RADIUS_METERS = 6_371_000


def distance_meters(start: tuple[float, float], end: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, start)
    lon2, lat2 = map(math.radians, end)
    delta_lon = lon2 - lon1
    delta_lat = lat2 - lat1
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return EARTH_RADIUS_METERS * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def parse_linestring_wkt(value: str) -> list[tuple[float, float]]:
    wkt = value.split(";", 1)[-1].strip()
    prefix = "LINESTRING("
    if not wkt.upper().startswith(prefix) or not wkt.endswith(")"):
        raise ValueError(f"unsupported linestring geometry: {value}")
    coordinates = []
    for point_text in wkt[len(prefix) : -1].split(","):
        lon_text, lat_text = point_text.strip().split()[:2]
        coordinates.append((float(lon_text), float(lat_text)))
    return coordinates


def midpoint(coordinates: list[tuple[float, float]]) -> tuple[float, float]:
    start, end = coordinates[0], coordinates[-1]
    return ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
