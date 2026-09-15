"""Tests for the enhanced merge events graph."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from src.state import CategoriesWithEvents
from src.research_events.merge_events.merge_events_graph import merge_events_app


@pytest.fixture
def sample_merge_input_state() -> dict:
    """Provide a sample input state for the enhanced merge events graph."""
    return {
        "existing_events": CategoriesWithEvents(
            early="Born in 1920 in Paris.",
            personal="Married in 1945.",
            career="Published first novel in 1950.",
            legacy="Won Nobel Prize in 1980.",
        ),
        "extracted_events": "He was born in New York City in 1920 and started writing at age 15. He published his first book in 1950 and won the Pulitzer Prize in 1985.",
        "research_question": "Research the life of the author",
    }


class MockToolCall:
    """Mock tool call for structured LLM responses."""

    def __init__(self, name, args):
        """Initialize mock tool call with name and args."""
        self.name = name
        self.args = args
    
    def __getitem__(self, key):
        """Make the mock tool call subscriptable."""
        if key == "name":
            return self.name
        elif key == "args":
            return self.args
        else:
            raise KeyError(f"Key {key} not found in MockToolCall")


class MockToolResponse:
    """Mock tool response for structured LLM responses."""

    def __init__(self, tool_calls=None):
        """Initialize mock tool response with tool calls."""
        self.tool_calls = tool_calls or []


@pytest.mark.asyncio
async def test_enhanced_merge_events_with_mocked_llm(sample_merge_input_state: dict):
    """Unit test for the enhanced merge events graph with mocked dependencies."""
    # --- Act: Execute the graph with patched dependencies ---
    with patch(
        "src.research_events.merge_events.merge_events_graph.create_tools_model"
    ) as mock_tools_model:
        
        # Mock the tools model response for categorization
        mock_tools_response = MockToolResponse([
            MockToolCall("RelevantEventsCategorized", {
                "early": "- Born in New York City in 1920",
                "personal": "",
                "career": "- Published first book in 1950", 
                "legacy": "- Won Pulitzer Prize in 1985",
            })
        ])
        mock_tools_instance = AsyncMock()
        mock_tools_instance.ainvoke.return_value = mock_tools_response
        mock_tools_model.return_value = mock_tools_instance
        
        result = await merge_events_app.ainvoke(sample_merge_input_state)

    # --- Assert: Verify the output ---
    assert "existing_events" in result
    existing_events = result["existing_events"]
    assert isinstance(existing_events, CategoriesWithEvents)
    
    # Verify that the tools model was called for categorization
    mock_tools_instance.ainvoke.assert_called()


@pytest.mark.asyncio
async def test_enhanced_merge_events_with_empty_content():
    """Test enhanced merge events with empty extracted content."""
    input_state = {
        "existing_events": CategoriesWithEvents(
            early="Born in 1920.",
            personal="Married in 1945.",
            career="Published in 1950.",
            legacy="Won prize in 1980.",
        ),
        "extracted_events": "",  # Empty content
        "research_question": "Test question",
    }

    result = await merge_events_app.ainvoke(input_state)
    
    # Should return existing events unchanged
    assert "existing_events" in result
    existing_events = result["existing_events"]
    assert existing_events.early == "Born in 1920."
    assert existing_events.personal == "Married in 1945."
    assert existing_events.career == "Published in 1950."
    assert existing_events.legacy == "Won prize in 1980."