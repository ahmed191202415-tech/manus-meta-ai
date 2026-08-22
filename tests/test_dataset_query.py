from app.core.dataset_query import nested_value, record_matches, sort_value


def test_nested_value_handles_empty_and_nested_paths():
    row = {"campaign": {"metrics": {"spend": "125.50"}}}

    assert nested_value(row, "campaign.metrics.spend") == "125.50"
    assert nested_value(row, "") == row
    assert nested_value(row, "campaign.missing") is None


def test_numeric_range_filter_compares_numeric_strings_without_type_error():
    row = {"spend": "125.50"}

    assert record_matches(row, {"spend": {"gte": 100, "lte": 130}}, None) is True
    assert record_matches(row, {"spend": {"gte": 126}}, None) is False


def test_date_range_filter_supports_iso_dates():
    row = {"date": "2026-08-22T10:00:00Z"}

    assert record_matches(row, {"date": {"gte": "2026-08-22", "lte": "2026-08-23"}}, None) is True


def test_mixed_dataset_values_can_always_be_sorted():
    values = [None, "alpha", 20, "10", False, "2026-08-22T10:00:00Z"]

    sorted_values = sorted(values, key=sort_value)

    assert sorted_values[-1] is None
    assert sorted_values.index("10") < sorted_values.index(20)


def test_search_handles_non_standard_serializable_values():
    assert record_matches({"value": {1, 2}}, {}, "1") is True

