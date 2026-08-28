"""Replace the SerpAPI-backed tools before ``agents.agent`` imports them.

The upstream tool modules import ``serpapi`` and ``langchain.pydantic_v1`` at
module scope. Neither is wanted here: there is no SerpAPI key and no egress,
and ``langchain.pydantic_v1`` was removed from the langchain line this image
installs. Registering replacements in ``sys.modules`` under the names
``agents.agent`` will import avoids both, and keeps the tool names and argument
schemas identical so the model's tool-calling behaviour is unchanged.
"""

from __future__ import annotations

import sys
import types
from typing import Optional

from pydantic import BaseModel, Field

from . import fixtures
from .network_guard import install as install_network_guard

_installed = False


def _flights_module() -> types.ModuleType:
    from langchain_core.tools import tool

    class FlightsInput(BaseModel):
        departure_airport: Optional[str] = Field(None, description='Departure airport code (IATA)')
        arrival_airport: Optional[str] = Field(None, description='Arrival airport code (IATA)')
        outbound_date: Optional[str] = Field(None, description='Parameter defines the outbound date. The format is YYYY-MM-DD. e.g. 2024-06-22')
        return_date: Optional[str] = Field(None, description='Parameter defines the return date. The format is YYYY-MM-DD. e.g. 2024-06-28')
        adults: Optional[int] = Field(1, description='Parameter defines the number of adults. Default to 1.')
        children: Optional[int] = Field(0, description='Parameter defines the number of children. Default to 0.')
        infants_in_seat: Optional[int] = Field(0, description='Parameter defines the number of infants in seat. Default to 0.')
        infants_on_lap: Optional[int] = Field(0, description='Parameter defines the number of infants on lap. Default to 0.')

    class FlightsInputSchema(BaseModel):
        params: FlightsInput

    @tool(args_schema=FlightsInputSchema)
    def flights_finder(params: FlightsInput):
        """
        Find flights using the Google Flights engine.

        Returns:
            dict: Flight search results.
        """
        return fixtures.best_flights(
            params.departure_airport,
            params.arrival_airport,
            params.outbound_date,
            params.return_date,
            params.adults or 1,
        )

    module = types.ModuleType("agents.tools.flights_finder")
    module.flights_finder = flights_finder
    module.FlightsInput = FlightsInput
    module.FlightsInputSchema = FlightsInputSchema
    return module


def _hotels_module() -> types.ModuleType:
    from langchain_core.tools import tool

    class HotelsInput(BaseModel):
        q: str = Field(description='Location of the hotel')
        check_in_date: str = Field(description='Check-in date. The format is YYYY-MM-DD. e.g. 2024-06-22')
        check_out_date: str = Field(description='Check-out date. The format is YYYY-MM-DD. e.g. 2024-06-28')
        sort_by: Optional[str] = Field(None, description='Parameter is used for sorting the results. Default is sort by highest rating')
        adults: Optional[int] = Field(1, description='Number of adults. Default to 1.')
        children: Optional[int] = Field(0, description='Number of children. Default to 0.')
        rooms: Optional[int] = Field(1, description='Number of rooms. Default to 1.')
        hotel_class: Optional[str] = Field(None, description='Parameter defines to include only certain hotel class in the results. for example- 2,3,4')

    class HotelsInputSchema(BaseModel):
        params: HotelsInput

    @tool(args_schema=HotelsInputSchema)
    def hotels_finder(params: HotelsInput):
        """
        Find hotels using the Google Hotels engine.

        Returns:
            dict: Hotel search results.
        """
        return fixtures.properties(
            params.q,
            params.check_in_date,
            params.check_out_date,
            params.hotel_class,
            params.adults or 1,
        )

    module = types.ModuleType("agents.tools.hotels_finder")
    module.hotels_finder = hotels_finder
    module.HotelsInput = HotelsInput
    module.HotelsInputSchema = HotelsInputSchema
    return module


def install() -> None:
    """Register the replacements; must run before ``agents.agent`` is imported."""
    global _installed
    if _installed:
        return
    if "agents.agent" in sys.modules:
        raise RuntimeError(
            "benchmark_mocks.install() ran after agents.agent was imported; "
            "the real SerpAPI tools are already bound to the model."
        )

    for name, module in (
        ("agents.tools.flights_finder", _flights_module()),
        ("agents.tools.hotels_finder", _hotels_module()),
    ):
        sys.modules[name] = module

    install_network_guard()
    _installed = True


def installed() -> bool:
    return _installed
