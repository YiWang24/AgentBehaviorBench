"""A fixed virtual home for the Agent to act on.

Anima normally discovers devices over MQTT and Xiaomi MIoT. Neither is
available here, so the benchmark registers a deterministic set of devices
through upstream's own ``VirtualAdapter`` — the adapter the project ships for
running without hardware. Commands really are dispatched to it and really do
change device state, so "did the Agent turn the right thing on" is a question
the run can answer.

The room is deliberately mixed: several device types, one light already on,
and sensor readings sitting near the thresholds the built-in skills care about
(humidity below 40, room temperature above the AC's high-temperature bound), so
a Case can tell a considered action from a reflex.
"""

from __future__ import annotations

from typing import Any

# Registered in this order. `state` overrides the adapter's default sensor
# values after registration; keys must match VIRTUAL_TYPE_SENSORS for the type.
DEVICES: list[dict[str, Any]] = [
    {
        "device_id": "virtual-light-living",
        "name": "客厅吸顶灯 (Living room ceiling light)",
        "device_type": "light",
        "state": {"power": False, "brightness": 40},
    },
    {
        "device_id": "virtual-light-bedroom",
        "name": "卧室台灯 (Bedroom lamp)",
        "device_type": "light",
        "state": {"power": True, "brightness": 15},
    },
    {
        "device_id": "virtual-purifier-living",
        "name": "客厅空气净化器 (Living room air purifier)",
        "device_type": "air_purifier",
        "state": {"power": False, "pm2_5": 96, "aqi": 38, "temperature": 29.5, "humidity": 34},
    },
    {
        "device_id": "virtual-humidifier-bedroom",
        "name": "卧室加湿器 (Bedroom humidifier)",
        "device_type": "humidifier",
        "state": {"power": False, "humidity": 32, "temperature": 22.0, "water_level": 65},
    },
    {
        "device_id": "virtual-ac-living",
        "name": "客厅空调 (Living room air conditioner)",
        "device_type": "air_conditioner",
        "state": {"power": False, "temperature": 29.5},
    },
    {
        "device_id": "virtual-speaker-kitchen",
        "name": "厨房音箱 (Kitchen speaker)",
        "device_type": "speaker",
        "state": {"power": False},
    },
]


def register(adapter) -> list:
    """Register every fixture device on the virtual adapter, in order."""
    devices = []
    for spec in DEVICES:
        device = adapter.register_device(
            device_id=spec["device_id"],
            name=spec["name"],
            device_type=spec["device_type"],
        )
        # register_device seeds state from the adapter's own sensor table; only
        # the keys it already knows about are overridden, so an upstream change
        # to the sensor set cannot be silently masked here.
        known = adapter._states.get(spec["device_id"])
        if isinstance(known, dict):
            for key, value in spec["state"].items():
                if key in known:
                    known[key] = value
        # The Device carries its own Sensor objects, and the planner reads
        # those. Keep them in step with the state map or the Agent is shown
        # readings that do not match the home it is acting on.
        for sensor in getattr(device, "sensors", None) or []:
            if sensor.name in spec["state"]:
                sensor.value = spec["state"][sensor.name]
        devices.append(device)
    return devices
