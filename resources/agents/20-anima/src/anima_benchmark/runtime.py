"""Assemble a Brain the way ``core/main.py`` does, minus the service layer.

Upstream's ``AnimaApp`` also starts an MQTT client, a discovery loop, a
scheduler, and a FastAPI server. None of that is needed to exercise the agent:
the Brain takes an event bus, a skill loader, and a memory store, and finds its
devices through an environment provider. This wires exactly those, backed by
the VirtualAdapter and the fixture home.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
from typing import Any

import benchmark_mocks

_runtime: "AnimaRuntime | None" = None


class AnimaRuntime:
    def __init__(self) -> None:
        from adapters.virtual.adapter import VirtualAdapter
        from core.brain.engine import Brain
        from core.brain.skill_loader import SkillLoader
        from core.devices.discovery import DiscoveryOrchestrator
        from core.events.bus import EventBus
        from core.memory.store import MemoryStore
        from core.runtime.config import settings
        from core.runtime.settings_store import SettingsStore

        self.bus = EventBus()
        self.memory = MemoryStore(base_dir=f"{settings.data_dir}/memory")
        self.skill_loader = SkillLoader(skills_dir=settings.skills_dir)
        self.settings_store = SettingsStore(f"{settings.data_dir}/config.json")
        self.adapter = VirtualAdapter(bus=self.bus)

        from . import home

        self.devices = home.register(self.adapter)

        # The chat graph dispatches device commands through the discovery
        # orchestrator, so it has to be real — commands genuinely reach the
        # virtual adapter and genuinely change device state. Registering the
        # fixture devices in its maps is what `core/main.py` does for its own
        # virtual devices.
        self.discovery = DiscoveryOrchestrator(bus=self.bus, adapters=[self.adapter])
        for device in self.devices:
            self.discovery.devices[device.device_id] = device
            self.discovery._adapter_map[device.device_id] = self.adapter

        self.brain = Brain(bus=self.bus, skill_loader=self.skill_loader, memory=self.memory)
        self.brain.set_environment_provider(lambda: list(self.devices))
        self.settings = settings

    def app_state(self) -> dict[str, Any]:
        """The slice of upstream's app state the chat graph reads."""
        return {
            "discovery": self.discovery,
            "brain": self.brain,
            "memory": self.memory,
            "bus": self.bus,
            "settings": self.settings_store,
            "_brain_event_queues": [],
        }

    def device_states(self) -> dict[str, dict[str, Any]]:
        """A snapshot of every virtual device's state, for the judge."""
        states = {}
        for device in self.devices:
            device_id = getattr(device, "device_id", None)
            if device_id is None:
                continue
            states[device_id] = {
                "name": getattr(device, "name", ""),
                "type": getattr(device, "type", ""),
                "state": dict(self.adapter._states.get(device_id, {})),
            }
        return states

    async def chat(self, message: str) -> dict[str, Any]:
        return await self.brain.handle_chat_message(message, self.app_state())

    async def aclose(self) -> None:
        await self.brain.close()


def _prepare_paths() -> None:
    """Point the writable paths at the tmpfs; the image root is read-only."""
    os.environ.setdefault("ANIMA_DATA_DIR", "/tmp/anima/data")
    os.environ.setdefault("ANIMA_SKILLS_DIR", "/opt/agent/skills")
    pathlib.Path(os.environ["ANIMA_DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    os.chdir("/tmp")


def runtime() -> AnimaRuntime:
    global _runtime
    if _runtime is None:
        _prepare_paths()
        benchmark_mocks.install_all()
        _runtime = AnimaRuntime()
    return _runtime


def graph():
    """The chat graph, for the LangGraph adapter's static entry point."""
    return runtime().brain._chat_graph


def ask(message: str) -> dict[str, Any]:
    return asyncio.run(runtime().chat(message))
