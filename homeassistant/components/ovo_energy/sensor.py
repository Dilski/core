"""Support for OVO Energy sensors."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from ovoenergy import OVODailyUsage
from ovoenergy.models import OVODailyElectricity, OVODailyGas
from ovoenergy.ovoenergy import OVOEnergy

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import OVOEnergyDeviceEntity
from .const import DATA_CLIENT, DATA_COORDINATOR, DOMAIN

SCAN_INTERVAL = timedelta(seconds=300)
PARALLEL_UPDATES = 4

KEY_LAST_ELECTRICITY_COST: Final = "last_electricity_cost"
KEY_ELECTRICITY_UNIT_RATE: Final = "electricity_unit_rate"
KEY_ELECTRICITY_STANDING_CHARGE: Final = "electricity_standing_charge"
KEY_LAST_GAS_COST: Final = "last_gas_cost"
KEY_GAS_UNIT_RATE: Final = "gas_unit_rate"
KEY_GAS_STANDING_CHARGE: Final = "gas_standing_charge"


def _latest_rate(
    usage: list[OVODailyElectricity] | list[OVODailyGas], rate: str
) -> float | None:
    """Return the most recent non-empty rate from the usage intervals."""
    for interval in reversed(usage):
        if interval is not None and interval.rates is not None:
            if (value := getattr(interval.rates, rate)) is not None:
                return value
    return None


@dataclass
class OVOEnergySensorEntityDescription(SensorEntityDescription):
    """Class describing System Bridge sensor entities."""

    value: Callable[[OVODailyUsage], StateType | datetime] = round


SENSOR_TYPES_ELECTRICITY: tuple[OVOEnergySensorEntityDescription, ...] = (
    OVOEnergySensorEntityDescription(
        key="last_electricity_reading",
        name="OVO Last Electricity Reading",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value=lambda usage: usage.electricity[-1].consumption,
    ),
    OVOEnergySensorEntityDescription(
        key=KEY_LAST_ELECTRICITY_COST,
        name="OVO Last Electricity Cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value=lambda usage: usage.electricity[-1].cost.amount
        if usage.electricity[-1].cost is not None
        else None,
    ),
    OVOEnergySensorEntityDescription(
        key=KEY_ELECTRICITY_UNIT_RATE,
        name="OVO Electricity Unit Rate",
        value=lambda usage: _latest_rate(usage.electricity, "anytime"),
    ),
    OVOEnergySensorEntityDescription(
        key=KEY_ELECTRICITY_STANDING_CHARGE,
        name="OVO Electricity Standing Charge",
        value=lambda usage: _latest_rate(usage.electricity, "standing"),
    ),
    OVOEnergySensorEntityDescription(
        key="last_electricity_start_time",
        name="OVO Last Electricity Start Time",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda usage: dt_util.as_utc(usage.electricity[-1].interval.start),
    ),
    OVOEnergySensorEntityDescription(
        key="last_electricity_end_time",
        name="OVO Last Electricity End Time",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda usage: dt_util.as_utc(usage.electricity[-1].interval.end),
    ),
)

SENSOR_TYPES_GAS: tuple[OVOEnergySensorEntityDescription, ...] = (
    OVOEnergySensorEntityDescription(
        key="last_gas_reading",
        name="OVO Last Gas Reading",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:gas-cylinder",
        value=lambda usage: usage.gas[-1].consumption,
    ),
    OVOEnergySensorEntityDescription(
        key=KEY_LAST_GAS_COST,
        name="OVO Last Gas Cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:cash-multiple",
        value=lambda usage: usage.gas[-1].cost.amount
        if usage.gas[-1].cost is not None
        else None,
    ),
    OVOEnergySensorEntityDescription(
        key=KEY_GAS_UNIT_RATE,
        name="OVO Gas Unit Rate",
        icon="mdi:cash-multiple",
        value=lambda usage: _latest_rate(usage.gas, "anytime"),
    ),
    OVOEnergySensorEntityDescription(
        key=KEY_GAS_STANDING_CHARGE,
        name="OVO Gas Standing Charge",
        icon="mdi:cash-multiple",
        value=lambda usage: _latest_rate(usage.gas, "standing"),
    ),
    OVOEnergySensorEntityDescription(
        key="last_gas_start_time",
        name="OVO Last Gas Start Time",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda usage: dt_util.as_utc(usage.gas[-1].interval.start),
    ),
    OVOEnergySensorEntityDescription(
        key="last_gas_end_time",
        name="OVO Last Gas End Time",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda usage: dt_util.as_utc(usage.gas[-1].interval.end),
    ),
)


def _set_rate_unit(
    description: OVOEnergySensorEntityDescription,
    usage: list[OVODailyElectricity] | list[OVODailyGas],
) -> None:
    """Set the currency unit on rate sensors from the latest cost."""
    cost = usage[-1].cost if usage[-1] is not None else None
    if cost is None or cost.currency_unit is None:
        return
    if description.key.endswith("_unit_rate"):
        description.native_unit_of_measurement = (
            f"{cost.currency_unit}/{UnitOfEnergy.KILO_WATT_HOUR}"
        )
    elif description.key.endswith("_standing_charge"):
        description.native_unit_of_measurement = f"{cost.currency_unit}/day"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OVO Energy sensor based on a config entry."""
    coordinator: DataUpdateCoordinator[OVODailyUsage] = hass.data[DOMAIN][
        entry.entry_id
    ][DATA_COORDINATOR]
    client: OVOEnergy = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]

    entities = []

    if coordinator.data:
        if coordinator.data.electricity:
            for description in SENSOR_TYPES_ELECTRICITY:
                _set_rate_unit(description, coordinator.data.electricity)
                if (
                    description.key == KEY_LAST_ELECTRICITY_COST
                    and coordinator.data.electricity[-1] is not None
                    and coordinator.data.electricity[-1].cost is not None
                ):
                    description.native_unit_of_measurement = (
                        coordinator.data.electricity[-1].cost.currency_unit
                    )
                entities.append(OVOEnergySensor(coordinator, description, client))
        if coordinator.data.gas:
            for description in SENSOR_TYPES_GAS:
                _set_rate_unit(description, coordinator.data.gas)
                if (
                    description.key == KEY_LAST_GAS_COST
                    and coordinator.data.gas[-1] is not None
                    and coordinator.data.gas[-1].cost is not None
                ):
                    description.native_unit_of_measurement = coordinator.data.gas[
                        -1
                    ].cost.currency_unit
                entities.append(OVOEnergySensor(coordinator, description, client))

    async_add_entities(entities, True)


class OVOEnergySensor(OVOEnergyDeviceEntity, SensorEntity):
    """Define a OVO Energy sensor."""

    coordinator: DataUpdateCoordinator[DataUpdateCoordinator[OVODailyUsage]]
    entity_description: OVOEnergySensorEntityDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[OVODailyUsage],
        description: OVOEnergySensorEntityDescription,
        client: OVOEnergy,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, client)
        self._attr_unique_id = f"{DOMAIN}_{client.account_id}_{description.key}"
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        """Return the state."""
        usage = self.coordinator.data
        return self.entity_description.value(usage)
