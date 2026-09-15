# tests/research_events/test_merge_events.py

"""Tests for the merge_events_graph."""

from unittest.mock import AsyncMock, patch

import pytest
from src.state import CategoriesWithEvents

# Imports are relative to the src directory (configured in pyproject.toml pythonpath)
from research_events.merge_events import merge_events_graph
from research_events.merge_events.merge_events_graph import merge_events_app

# ## Refactoring Note: Import the module containing the object to be patched.
# This makes the patch call cleaner and more robust against refactoring.


@pytest.fixture
def sample_input_state() -> dict:
    """Provide a sample input state for the merge_events_app graph."""
    return {
        "existing_events": CategoriesWithEvents(
            early="Born in 1920 in Paris.",
            personal="Married in 1945.",
            career="Published first novel in 1950.",
            legacy="Won Nobel Prize in 1980.",
        ),
        "raw_extracted_events": "Born in 1920 in Paris, France. Started writing poetry at age 15. Moved to London in 1942.",
    }


class MockResponse:
    """Mock response class for LLM responses."""

    def __init__(self, content):
        """Initialize mock response with content."""
        self.content = content


@pytest.fixture
def mock_structured_llm():
    """Provide a reusable mock for model_for_structured with configurable responses."""

    def create_mock_model(categorized_events, merge_responses):
        """Create a configured mock model."""
        mock_model = AsyncMock()

        # Mock the structured output chain
        mock_structured_llm = AsyncMock()
        mock_structured_llm.ainvoke.return_value = categorized_events
        mock_model.with_structured_output.return_value = mock_structured_llm

        # Create async functions that return the mock responses
        async def mock_ainvoke(prompt):
            return merge_responses.pop(0)

        # Mock the regular invoke calls for merging
        mock_model.ainvoke = mock_ainvoke

        return mock_model

    return create_mock_model


@pytest.mark.skip(reason="Skip mocked LLM test for now")
@pytest.mark.asyncio
async def test_merge_events_with_mocked_llm(
    sample_input_state: dict, mock_structured_llm
):
    """Unit test for the merge events graph with a mocked LLM."""
    # --- Arrange: Mock Data Setup ---
    mock_categorized_events = CategoriesWithEvents(
        early="Born in 1920 in Paris, France. Started writing poetry at age 15.",
        personal="Moved to London in 1942.",
        career="",
        legacy="",
    )

    mock_merge_responses = [
        MockResponse(
            "Born in 1920 in Paris, France. Started writing poetry at age 15."
        ),
        MockResponse("Married in 1945. Moved to London in 1942."),
        MockResponse("Published first novel in 1950."),
        MockResponse("Won Nobel Prize in 1980."),
    ]

    # --- Act: Execute the graph with patched dependencies ---
    with patch.object(merge_events_graph, "model_for_structured") as mock_model:
        # Configure the mock using the reusable fixture
        llm_mock = mock_structured_llm(mock_categorized_events, mock_merge_responses)

        # Apply the mock configuration
        mock_model.ainvoke = llm_mock.ainvoke
        mock_model.with_structured_output.return_value = (
            llm_mock.with_structured_output.return_value
        )

        result = await merge_events_app.ainvoke(sample_input_state)

    # --- Assert: Verify the output ---
    assert "existing_events" in result
    merged_events = result["existing_events"]

    assert isinstance(merged_events, CategoriesWithEvents)
    assert (
        merged_events.early
        == "Born in 1920 in Paris, France. Started writing poetry at age 15."
    )
    assert merged_events.personal == "Married in 1945. Moved to London in 1942."
    assert merged_events.career == "Published first novel in 1950."
    assert merged_events.legacy == "Won Nobel Prize in 1980."


@pytest.mark.skip(reason="Skip real LLM test for now")
@pytest.mark.llm
@pytest.mark.asyncio
async def test_merge_events_with_real_llm(sample_input_state: dict):
    """Integration test for the merge events graph with real LLM calls."""
    # --- Act ---
    result = await merge_events_app.ainvoke(sample_input_state)

    # --- Assert ---
    assert "existing_events" in result
    merged = result["existing_events"]
    assert isinstance(merged, CategoriesWithEvents)

    all_merged_text = " ".join(vars(merged).values())
    # Check that key old and new info is present somewhere
    print("merged", merged)
    print(f"merged.early: {merged.early}")
    print(f"merged.personal: {merged.personal}")
    print(f"merged.career: {merged.career}")
    print(f"merged.legacy: {merged.legacy}")
    assert "1920" in merged.early
    assert "Married" in merged.personal
    assert "Nobel Prize" in merged.legacy
    assert "London" in merged.personal
