from datetime import datetime
import logging

from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEvent,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import (
    AddConfigEntryEntitiesCallback,
)
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Water Babies Calendar platform."""
    coordinator = config_entry.runtime_data

    async_add_entities(
        [WaterBabiesCalendar(coordinator, config_entry)]
    )


class WaterBabiesCalendar(
    CoordinatorEntity,
    CalendarEntity,
):
    """A calendar entity for Water Babies lessons."""

    def __init__(self, coordinator, config_entry) -> None:
        """Initialize the calendar."""
        super().__init__(coordinator)

        self._config_entry = config_entry
        self._attr_name = (
            f"Water Babies "
            f"{config_entry.data['username']}"
        )
        self._attr_unique_id = (
            f"{config_entry.entry_id}_calendar"
        )

    def _parse_datetime(self, value: str) -> datetime:
        """Parse API datetime into HA timezone-aware datetime."""
        dt = datetime.fromisoformat(value)

        # API returns naive local times
        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=dt_util.DEFAULT_TIME_ZONE
            )

        return dt

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event."""
        now = dt_util.now()

        next_event = None
        next_start = None

        for lesson in self.coordinator.data:
            start_time = self._parse_datetime(
                lesson["start"]
            )
            end_time = self._parse_datetime(
                lesson["end"]
            )

            if start_time <= now:
                continue

            if (
                next_start is None
                or start_time < next_start
            ):
                next_start = start_time

                next_event = CalendarEvent(
                    summary=(
                        f"{lesson['child_name']} - "
                        f"{lesson['title']}"
                    ),
                    start=start_time,
                    end=end_time,
                    location=lesson["location"],
                    description=(
                        f"Child: "
                        f"{lesson['child_name']}\n"
                        f"Location: "
                        f"{lesson['location']}"
                    ),
                )

        return next_event

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return events within a date range."""
        events = []

        for lesson in self.coordinator.data:
            start_time = self._parse_datetime(
                lesson["start"]
            )
            end_time = self._parse_datetime(
                lesson["end"]
            )

            if (
                start_time < end_date
                and end_time > start_date
            ):
                events.append(
                    CalendarEvent(
                        summary=(
                            f"{lesson['child_name']} - "
                            f"{lesson['title']}"
                        ),
                        start=start_time,
                        end=end_time,
                        location=lesson["location"],
                        description=(
                            f"Child: "
                            f"{lesson['child_name']}\n"
                            f"Location: "
                            f"{lesson['location']}"
                        ),
                    )
                )

        return events