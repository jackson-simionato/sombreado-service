"""Publish derives the direction advice denorm from staged segment rows (#130)."""

from sombreado.store.generation_writes import advice_segments_by_direction
from sombreado.store.sample_data import sample_generation_rows


def test_advice_segments_by_direction_mirrors_segment_rows_in_sequence_order():
    rows = sample_generation_rows(generation_suffix="a")

    denorm = advice_segments_by_direction(rows["route_segments"])

    direction_id = rows["route_directions"][0]["id"]
    segments = rows["route_segments"]
    assert [item["public_id"] for item in denorm[direction_id]] == [segment["id"] for segment in segments]
    assert [item["sequence"] for item in denorm[direction_id]] == [1, 2]
    assert denorm[direction_id][0]["bearing_degrees"] == segments[0]["bearing_degrees"]
    assert denorm[direction_id][1]["cumulative_distance_meters"] == segments[1]["cumulative_distance_meters"]
    assert denorm[direction_id][0]["coordinates"] == [
        [-48.53424287871695, -27.58967698020161],
        [-48.53429001602508, -27.58967384329425],
    ]


def test_advice_segments_by_direction_orders_out_of_order_rows():
    rows = sample_generation_rows(generation_suffix="a")
    reversed_segments = list(reversed(rows["route_segments"]))

    denorm = advice_segments_by_direction(reversed_segments)

    direction_id = rows["route_directions"][0]["id"]
    assert [item["sequence"] for item in denorm[direction_id]] == [1, 2]


def test_advice_segments_by_direction_omits_directions_without_segments():
    assert advice_segments_by_direction([]) == {}
