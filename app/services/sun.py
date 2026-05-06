from datetime import datetime

from astral import Observer
from astral.sun import azimuth, elevation

from app.schemas import SunPosition


def sun_position(*, lat: float, lng: float, dt: datetime) -> SunPosition:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("dt must be timezone-aware")
    observer = Observer(latitude=lat, longitude=lng)
    return SunPosition(azimuth=azimuth(observer, dt), elevation=elevation(observer, dt))
