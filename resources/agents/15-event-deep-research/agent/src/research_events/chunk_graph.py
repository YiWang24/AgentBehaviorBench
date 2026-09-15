from typing import Dict, List, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field
from src.configuration import Configuration
from src.llm_service import create_llm_chunk_model


class BiographicEventCheck(BaseModel):
    contains_biographic_event: bool = Field(
        description="Whether the text chunk contains biographical events"
    )


class ChunkResult(BaseModel):
    content: str
    contains_biographic_event: bool = Field(
        description="Whether the text chunk contains biographical events"
    )


class ChunkState(TypedDict):
    text: str
    chunks: List[str]
    results: Dict[str, ChunkResult]


def split_text(state: ChunkState) -> ChunkState:
    """Split text into smaller chunks."""
    text = state["text"]
    chunk_size = 2000
    chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
    return {"chunks": chunks}


def check_chunk_for_events(state: ChunkState, config) -> ChunkState:
    """Check each chunk for biographical events using structured output."""
    model = create_llm_chunk_model(config, BiographicEventCheck)
    results = {}

    for i, chunk in enumerate(state["chunks"]):
        prompt = f"""
        Analyze this text chunk and determine if it contains SPECIFIC biographical events.
        
        ONLY mark as true if the chunk contains:
        - Birth/death dates or locations
        - Marriage ceremonies or relationships
        - Educational enrollment or graduation
        - Career appointments or job changes
        - Awards, prizes, or honors received
        - Relocations to new cities/countries
        - Major discoveries or inventions
        
        DO NOT mark as true for:
        - General descriptions or background information
        - Character traits or personality descriptions
        - General statements about time periods
        - Descriptions of places without personal connection
        - General knowledge or context
        
        The event must be specific and concrete, not general background.
        
        Text chunk: "{chunk}"
        """

        result = model.invoke(prompt)
        results[f"chunk_{i}"] = ChunkResult(
            content=chunk, contains_biographic_event=result.contains_biographic_event
        )

    return {"results": results}


def create_biographic_event_graph() -> CompiledStateGraph:
    """Create and return the biographic event detection graph."""
    graph = StateGraph(ChunkState, config_schema=Configuration)

    graph.add_node("split_text", split_text)
    graph.add_node("check_events", check_chunk_for_events)

    graph.add_edge(START, "split_text")
    graph.add_edge("split_text", "check_events")
    graph.add_edge("check_events", END)

    return graph.compile()


graph = create_biographic_event_graph()
