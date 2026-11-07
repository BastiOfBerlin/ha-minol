"""Tests for MinolDataCoordinator."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.minol import MinolRuntimeData
from custom_components.minol.const import CONF_SCAN_INTERVAL, DOMAIN
from custom_components.minol.coordinator import MinolDataCoordinator

from .conftest import MOCK_FETCH_ALL_RESULT, MOCK_USER_INPUT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coordinator(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    session_data: dict | None = None,
) -> MinolDataCoordinator:
    """Create a coordinator and set a minimal runtime_data on the entry."""
    coord = MinolDataCoordinator(hass, config_entry)
    runtime = MagicMock()
    runtime.session_data = session_data if session_data is not None else {}
    config_entry.runtime_data = MinolRuntimeData(coordinator=coord, session_data=runtime.session_data)
    return coord


# ---------------------------------------------------------------------------
# update_interval from options
# ---------------------------------------------------------------------------


async def test_update_interval_default(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Default update interval is 6 hours."""
    coord = _make_coordinator(hass, mock_config_entry)
    assert coord.update_interval == timedelta(hours=6)


async def test_update_interval_custom(
    hass: HomeAssistant,
) -> None:
    """Custom scan_interval option sets update_interval accordingly."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_USER_INPUT,
        unique_id="123456789012",
        options={CONF_SCAN_INTERVAL: 12},
    )
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass, entry)
    assert coord.update_interval == timedelta(hours=12)


# ---------------------------------------------------------------------------
# _async_update_data
# ---------------------------------------------------------------------------


async def test_update_data_success(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Successful update returns fetch_all result."""
    coord = _make_coordinator(hass, mock_config_entry)

    mock_instance = MagicMock()
    mock_instance.login = AsyncMock(return_value=None)
    mock_instance.fetch_all = AsyncMock(return_value=MOCK_FETCH_ALL_RESULT)

    with (
        patch("custom_components.minol.coordinator.MinolScraper", return_value=mock_instance),
        patch("custom_components.minol.coordinator.create_session"),
    ):
        result = await coord._async_update_data()

    assert result == MOCK_FETCH_ALL_RESULT
    mock_instance.login.assert_called_once()
    mock_instance.fetch_all.assert_called_once()


async def test_update_data_session_updated(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """When login returns a dict, session_data is updated in place."""
    session_data: dict = {}
    coord = _make_coordinator(hass, mock_config_entry, session_data=session_data)
    mock_config_entry.runtime_data.session_data = session_data

    new_tokens = {"token": "abc123"}
    mock_instance = MagicMock()
    mock_instance.login = AsyncMock(return_value=new_tokens)
    mock_instance.fetch_all = AsyncMock(return_value=MOCK_FETCH_ALL_RESULT)

    with (
        patch("custom_components.minol.coordinator.MinolScraper", return_value=mock_instance),
        patch("custom_components.minol.coordinator.create_session"),
    ):
        await coord._async_update_data()

    assert session_data == new_tokens


async def test_update_data_session_unchanged_on_none(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """When login returns None, session_data is not modified."""
    session_data: dict = {"token": "existing"}
    coord = _make_coordinator(hass, mock_config_entry, session_data=session_data)
    mock_config_entry.runtime_data.session_data = session_data

    mock_instance = MagicMock()
    mock_instance.login = AsyncMock(return_value=None)
    mock_instance.fetch_all = AsyncMock(return_value=MOCK_FETCH_ALL_RESULT)

    with (
        patch("custom_components.minol.coordinator.MinolScraper", return_value=mock_instance),
        patch("custom_components.minol.coordinator.create_session"),
    ):
        await coord._async_update_data()

    assert session_data == {"token": "existing"}


async def test_update_data_auth_error(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Auth RuntimeError raises ConfigEntryAuthFailed."""
    coord = _make_coordinator(hass, mock_config_entry)

    mock_instance = MagicMock()
    mock_instance.login = AsyncMock(
        side_effect=RuntimeError("Authentication failed")
    )

    with (
        patch("custom_components.minol.coordinator.MinolScraper", return_value=mock_instance),
        patch("custom_components.minol.coordinator.create_session"),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await coord._async_update_data()


async def test_update_data_runtime_error(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Non-auth RuntimeError raises UpdateFailed."""
    coord = _make_coordinator(hass, mock_config_entry)

    mock_instance = MagicMock()
    mock_instance.login = AsyncMock(
        side_effect=RuntimeError("portal is down")
    )

    with (
        patch("custom_components.minol.coordinator.MinolScraper", return_value=mock_instance),
        patch("custom_components.minol.coordinator.create_session"),
        pytest.raises(UpdateFailed),
    ):
        await coord._async_update_data()


async def test_update_data_generic_exception(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Unexpected exception from fetch_all raises UpdateFailed."""
    coord = _make_coordinator(hass, mock_config_entry)

    mock_instance = MagicMock()
    mock_instance.login = AsyncMock(return_value=None)
    mock_instance.fetch_all = AsyncMock(side_effect=Exception("unexpected"))

    with (
        patch("custom_components.minol.coordinator.MinolScraper", return_value=mock_instance),
        patch("custom_components.minol.coordinator.create_session"),
        pytest.raises(UpdateFailed),
    ):
        await coord._async_update_data()


# ---------------------------------------------------------------------------
# async_import_historical_data
# ---------------------------------------------------------------------------


def _make_mock_recorder(
    anchor_stats: dict | None = None,
    last_stat_before: dict | None = None,
) -> tuple:
    """Return (mock_recorder_instance, fake_statistics_during_period,
    fake_get_last_statistics, fake_import_statistics, captured_imports_list).

    ``anchor_stats`` seeds statistics_during_period (used to find the
    backward-accumulation anchor after the import range). ``last_stat_before``
    seeds get_last_statistics (used to seed forward accumulation when no
    anchor is found).
    """
    captured: list = []

    def fake_import_statistics(hass, metadata, stats):
        captured.append({"metadata": metadata, "stats": stats})

    async def fake_executor_job(func, *args):
        return func(*args)

    mock_recorder_instance = MagicMock()
    mock_recorder_instance.async_add_executor_job = fake_executor_job

    def fake_statistics_during_period(hass, start_time, end_time, statistic_ids, period, units, types):
        return anchor_stats or {}

    def fake_get_last_statistics(hass, count, entity_id, convert, statistic_types):
        return last_stat_before or {}

    return (
        mock_recorder_instance,
        fake_statistics_during_period,
        fake_get_last_statistics,
        fake_import_statistics,
        captured,
    )


def _register_entity(hass: HomeAssistant, room_name: str, consumption_type: str) -> str:
    """Register a sensor entity for (room_name, consumption_type) and return its entity_id."""
    from homeassistant.helpers import entity_registry as er
    from homeassistant.util import slugify

    registry = er.async_get(hass)
    user_num = MOCK_USER_INPUT["user_num"]
    unique_id = f"{user_num}_{slugify(room_name)}_{slugify(consumption_type)}"
    return registry.async_get_or_create("sensor", DOMAIN, unique_id).entity_id


async def test_import_historical_data_basic(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Statistics are imported with correct cumulative running_sum (forward, no anchor)."""
    coord = _make_coordinator(hass, mock_config_entry)
    mock_config_entry.runtime_data.session_data = {}

    mock_instance = MagicMock()
    mock_instance.login = AsyncMock(return_value=None)
    mock_instance.fetch_all = AsyncMock(return_value=MOCK_FETCH_ALL_RESULT)

    recorder_instance, fake_anchor, fake_get_last, fake_import, captured = _make_mock_recorder()

    entity_id = _register_entity(hass, "Wohnung 1", "heating")

    with (
        patch("custom_components.minol.coordinator.MinolScraper", return_value=mock_instance),
        patch("custom_components.minol.coordinator.create_session"),
        patch("homeassistant.components.recorder.get_instance", return_value=recorder_instance),
        patch("homeassistant.components.recorder.statistics.statistics_during_period", fake_anchor),
        patch("homeassistant.components.recorder.statistics.get_last_statistics", fake_get_last),
        patch("homeassistant.components.recorder.statistics.async_import_statistics", fake_import),
    ):
        await coord.async_import_historical_data("202501", "202502")

    # Should have called import for heating room (and warm_water and cold_water if they have entities too)
    heating_calls = [c for c in captured if c["metadata"]["statistic_id"] == entity_id]
    assert len(heating_calls) >= 1

    stats = heating_calls[0]["stats"]
    # running_sum for 202501=120.5, 202502=95.3 → 120.5, 215.8
    values = [s["sum"] for s in stats]
    assert values[0] == pytest.approx(120.5)
    assert values[1] == pytest.approx(215.8)


async def test_import_historical_data_skips_null_months(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Months with null values are excluded from imported statistics."""
    coord = _make_coordinator(hass, mock_config_entry)

    data_with_nulls = {
        "heating": {
            "unit": "KWH",
            "rooms": {
                "Wohnung 1": {
                    "monthly": {"202501": 100.0, "202502": None, "202503": 50.0},
                }
            },
        }
    }
    mock_instance = MagicMock()
    mock_instance.login = AsyncMock(return_value=None)
    mock_instance.fetch_all = AsyncMock(return_value=data_with_nulls)

    entity_id = _register_entity(hass, "Wohnung 1", "heating")

    recorder_instance, fake_anchor, fake_get_last, fake_import, captured = _make_mock_recorder()

    with (
        patch("custom_components.minol.coordinator.MinolScraper", return_value=mock_instance),
        patch("custom_components.minol.coordinator.create_session"),
        patch("homeassistant.components.recorder.get_instance", return_value=recorder_instance),
        patch("homeassistant.components.recorder.statistics.statistics_during_period", fake_anchor),
        patch("homeassistant.components.recorder.statistics.get_last_statistics", fake_get_last),
        patch("homeassistant.components.recorder.statistics.async_import_statistics", fake_import),
    ):
        await coord.async_import_historical_data("202501", "202503")

    heating_calls = [c for c in captured if c["metadata"]["statistic_id"] == entity_id]
    assert len(heating_calls) == 1
    # Only 2 non-null months (202501, 202503) should appear
    assert len(heating_calls[0]["stats"]) == 2


async def test_import_historical_data_backward_anchor_continuity(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """When a statistic exists after the range, accumulation runs backward from it with no spike."""
    coord = _make_coordinator(hass, mock_config_entry)

    data = {
        "heating": {
            "unit": "KWH",
            "rooms": {
                "Wohnung 1": {
                    "monthly": {"202501": 100.0, "202502": 50.0},
                }
            },
        }
    }
    mock_instance = MagicMock()
    mock_instance.login = AsyncMock(return_value=None)
    mock_instance.fetch_all = AsyncMock(return_value=data)

    entity_id = _register_entity(hass, "Wohnung 1", "heating")

    from datetime import datetime, timezone
    anchor_start = datetime(2025, 3, 1, tzinfo=timezone.utc).timestamp()
    anchor_stats = {entity_id: [{"start": anchor_start, "sum": 300.0}]}

    recorder_instance, fake_anchor, fake_get_last, fake_import, captured = _make_mock_recorder(
        anchor_stats=anchor_stats
    )

    with (
        patch("custom_components.minol.coordinator.MinolScraper", return_value=mock_instance),
        patch("custom_components.minol.coordinator.create_session"),
        patch("homeassistant.components.recorder.get_instance", return_value=recorder_instance),
        patch("homeassistant.components.recorder.statistics.statistics_during_period", fake_anchor),
        patch("homeassistant.components.recorder.statistics.get_last_statistics", fake_get_last),
        patch("homeassistant.components.recorder.statistics.async_import_statistics", fake_import),
    ):
        await coord.async_import_historical_data("202501", "202502")

    heating_calls = [c for c in captured if c["metadata"]["statistic_id"] == entity_id]
    assert len(heating_calls) == 1
    stats = heating_calls[0]["stats"]
    # anchor sum=300; working backward: 202502 -> 300-50=250, 202501 -> 250-100=150
    assert stats[0]["sum"] == pytest.approx(150.0)
    assert stats[1]["sum"] == pytest.approx(250.0)
    # Continuity at the boundary: anchor_sum - last_imported_sum == last month's delta
    assert 300.0 - stats[-1]["sum"] == pytest.approx(50.0)
    # No delta in the imported series is negative (monotonic, no spike)
    assert stats[1]["sum"] - stats[0]["sum"] == pytest.approx(100.0)


async def test_import_historical_data_forward_from_zero_when_no_anchor(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """With nothing before or after the range, accumulation starts fresh from zero."""
    coord = _make_coordinator(hass, mock_config_entry)

    data = {
        "heating": {
            "unit": "KWH",
            "rooms": {
                "Wohnung 1": {
                    "monthly": {"202501": 80.0},
                }
            },
        }
    }
    mock_instance = MagicMock()
    mock_instance.login = AsyncMock(return_value=None)
    mock_instance.fetch_all = AsyncMock(return_value=data)

    entity_id = _register_entity(hass, "Wohnung 1", "heating")

    recorder_instance, fake_anchor, fake_get_last, fake_import, captured = _make_mock_recorder()

    with (
        patch("custom_components.minol.coordinator.MinolScraper", return_value=mock_instance),
        patch("custom_components.minol.coordinator.create_session"),
        patch("homeassistant.components.recorder.get_instance", return_value=recorder_instance),
        patch("homeassistant.components.recorder.statistics.statistics_during_period", fake_anchor),
        patch("homeassistant.components.recorder.statistics.get_last_statistics", fake_get_last),
        patch("homeassistant.components.recorder.statistics.async_import_statistics", fake_import),
    ):
        await coord.async_import_historical_data("202501", "202501")

    heating_calls = [c for c in captured if c["metadata"]["statistic_id"] == entity_id]
    assert heating_calls[0]["stats"][0]["sum"] == pytest.approx(80.0)


async def test_import_historical_data_seeds_from_existing(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Prior stat sum is used as initial running_sum seed when no anchor exists after the range."""
    coord = _make_coordinator(hass, mock_config_entry)

    data = {
        "heating": {
            "unit": "KWH",
            "rooms": {
                "Wohnung 1": {
                    "monthly": {"202502": 50.0},
                }
            },
        }
    }
    mock_instance = MagicMock()
    mock_instance.login = AsyncMock(return_value=None)
    mock_instance.fetch_all = AsyncMock(return_value=data)

    entity_id = _register_entity(hass, "Wohnung 1", "heating")

    # Simulate existing stat from 202501 with sum=120.5, and nothing after the range.
    from datetime import datetime, timezone
    prior_start = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
    existing_stat = {entity_id: [{"start": prior_start, "sum": 120.5}]}

    recorder_instance, fake_anchor, _, fake_import, captured = _make_mock_recorder(
        last_stat_before=existing_stat
    )

    with (
        patch("custom_components.minol.coordinator.MinolScraper", return_value=mock_instance),
        patch("custom_components.minol.coordinator.create_session"),
        patch("homeassistant.components.recorder.get_instance", return_value=recorder_instance),
        patch("homeassistant.components.recorder.statistics.statistics_during_period", fake_anchor),
        patch("homeassistant.components.recorder.statistics.get_last_statistics",
              lambda hass, count, eid, convert, types: existing_stat if eid == entity_id else {}),
        patch("homeassistant.components.recorder.statistics.async_import_statistics", fake_import),
    ):
        await coord.async_import_historical_data("202502", "202502")

    heating_calls = [c for c in captured if c["metadata"]["statistic_id"] == entity_id]
    # running_sum should be 120.5 (seed) + 50.0 = 170.5
    assert heating_calls[0]["stats"][0]["sum"] == pytest.approx(170.5)


async def test_import_historical_data_skips_missing_entity(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Rooms with no registered entity are skipped without error."""
    coord = _make_coordinator(hass, mock_config_entry)

    mock_instance = MagicMock()
    mock_instance.login = AsyncMock(return_value=None)
    mock_instance.fetch_all = AsyncMock(return_value=MOCK_FETCH_ALL_RESULT)

    recorder_instance, fake_anchor, fake_get_last, fake_import, captured = _make_mock_recorder()

    # No entities registered — import should skip all rooms silently
    with (
        patch("custom_components.minol.coordinator.MinolScraper", return_value=mock_instance),
        patch("custom_components.minol.coordinator.create_session"),
        patch("homeassistant.components.recorder.get_instance", return_value=recorder_instance),
        patch("homeassistant.components.recorder.statistics.statistics_during_period", fake_anchor),
        patch("homeassistant.components.recorder.statistics.get_last_statistics", fake_get_last),
        patch("homeassistant.components.recorder.statistics.async_import_statistics", fake_import),
    ):
        await coord.async_import_historical_data("202501", "202502")

    assert captured == []


async def test_import_historical_data_consumption_types_filter(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Only the requested consumption types are imported."""
    coord = _make_coordinator(hass, mock_config_entry)

    mock_instance = MagicMock()
    mock_instance.login = AsyncMock(return_value=None)
    mock_instance.fetch_all = AsyncMock(return_value=MOCK_FETCH_ALL_RESULT)

    heating_id = _register_entity(hass, "Wohnung 1", "heating")
    warm_water_id = _register_entity(hass, "Wohnung 1", "warm_water")
    cold_water_id = _register_entity(hass, "Wohnung 1", "cold_water")

    recorder_instance, fake_anchor, fake_get_last, fake_import, captured = _make_mock_recorder()

    with (
        patch("custom_components.minol.coordinator.MinolScraper", return_value=mock_instance),
        patch("custom_components.minol.coordinator.create_session"),
        patch("homeassistant.components.recorder.get_instance", return_value=recorder_instance),
        patch("homeassistant.components.recorder.statistics.statistics_during_period", fake_anchor),
        patch("homeassistant.components.recorder.statistics.get_last_statistics", fake_get_last),
        patch("homeassistant.components.recorder.statistics.async_import_statistics", fake_import),
    ):
        await coord.async_import_historical_data(
            "202501", "202502", consumption_types=["heating"]
        )

    statistic_ids = {c["metadata"]["statistic_id"] for c in captured}
    assert statistic_ids == {heating_id}
    assert warm_water_id not in statistic_ids
    assert cold_water_id not in statistic_ids


async def test_import_historical_data_dry_run_writes_nothing(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """dry_run=True computes stats but never calls async_import_statistics."""
    coord = _make_coordinator(hass, mock_config_entry)

    data = {
        "heating": {
            "unit": "KWH",
            "rooms": {
                "Wohnung 1": {
                    "monthly": {"202501": 100.0},
                }
            },
        }
    }
    mock_instance = MagicMock()
    mock_instance.login = AsyncMock(return_value=None)
    mock_instance.fetch_all = AsyncMock(return_value=data)

    _register_entity(hass, "Wohnung 1", "heating")

    recorder_instance, fake_anchor, fake_get_last, fake_import, captured = _make_mock_recorder()

    with (
        patch("custom_components.minol.coordinator.MinolScraper", return_value=mock_instance),
        patch("custom_components.minol.coordinator.create_session"),
        patch("homeassistant.components.recorder.get_instance", return_value=recorder_instance),
        patch("homeassistant.components.recorder.statistics.statistics_during_period", fake_anchor),
        patch("homeassistant.components.recorder.statistics.get_last_statistics", fake_get_last),
        patch("homeassistant.components.recorder.statistics.async_import_statistics", fake_import),
    ):
        await coord.async_import_historical_data("202501", "202501", dry_run=True)

    assert captured == []
