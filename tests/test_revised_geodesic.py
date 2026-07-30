"""WGS84-local point-to-segment distance — literals from prototype @ fffe074."""

from pytest import approx

from sombreado.store.geodesic import order_nearby_rows, point_to_segment_meters

# PostGIS 3.4 geography ST_Distance on real Floripa route segments near the
# measured worst workload point (short chords, typical publication geometry).
_POSTGIS_CASES = (
    (
        -27.58967541174793,
        -48.53426644737102,
        -27.58967698020161,
        -48.53424287871695,
        -27.58967384329425,
        -48.53429001602508,
        0.0,
    ),
    (
        -27.58967541174793,
        -48.53426644737102,
        -27.58967875783012,
        -48.53423370052804,
        -27.58966823891881,
        -48.53428961785253,
        0.30511292,
    ),
    (
        -27.58967541174793,
        -48.53426644737102,
        -27.58968714319034,
        -48.53429463598153,
        -27.58969759332988,
        -48.53423889235127,
        1.84518372,
    ),
    (
        -27.58967541174793,
        -48.53426644737102,
        -27.58963919703241,
        -48.53432500641638,
        -27.58970667048621,
        -48.53407698828636,
        2.14972066,
    ),
)


def test_point_to_segment_matches_postgis_geography_within_a_centimeter():
    for lat, lng, start_lat, start_lng, end_lat, end_lng, expected in _POSTGIS_CASES:
        assert point_to_segment_meters(
            lat,
            lng,
            start_lat,
            start_lng,
            end_lat,
            end_lng,
        ) == approx(expected, abs=0.01)


def test_point_to_segment_zero_length_uses_endpoint_distance():
    distance = point_to_segment_meters(
        -27.58967541174793,
        -48.53426644737102,
        -27.58967541174793,
        -48.53426644737102,
        -27.58967541174793,
        -48.53426644737102,
    )
    assert distance == approx(0.0, abs=1e-9)


def test_order_nearby_rows_sorts_by_code_within_tie_band():
    rows = [
        ("332", "Route 332", 1660.69),
        ("110", "Route 110", 1657.60),
        ("212", "Route 212", 1655.61),
        ("184", "Route 184", 1659.04),
        ("320", "Route 320", 1655.61),
    ]
    result = order_nearby_rows(rows)
    codes = [row[0] for row in result]
    assert codes == ["110", "184", "212", "320", "332"]


def test_order_nearby_rows_sample_445_documents_residual_2cm_split():
    rows = [
        ("212", "Route 212", 1655.59445598),
        ("320", "Route 320", 1655.59445598),
        ("184", "Route 184", 1657.59932167),
        ("110", "Route 110", 1659.03513482),
        ("332", "Route 332", 1660.67021846),
    ]
    result = order_nearby_rows(rows)
    codes = [row[0] for row in result]
    assert codes == ["212", "320", "110", "184", "332"]


def test_order_nearby_rows_separates_groups_beyond_2m_gap():
    rows = [
        ("B", "Route B", 10.0),
        ("A", "Route A", 11.5),
        ("D", "Route D", 15.0),
        ("C", "Route C", 16.0),
    ]
    result = order_nearby_rows(rows)
    codes = [row[0] for row in result]
    assert codes == ["A", "B", "C", "D"]


def test_order_nearby_rows_does_not_merge_across_barely_over_2m_gap():
    rows = [
        ("847", "Route 847", 100.0),
        ("470", "Route 470", 102.001),
    ]
    result = order_nearby_rows(rows)
    codes = [row[0] for row in result]
    assert codes == ["847", "470"]


def test_order_nearby_rows_empty():
    assert order_nearby_rows([]) == ()
