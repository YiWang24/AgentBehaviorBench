categorize_events_prompt = """
You are a helpful assistant that will categorize the events into the 4 categories.

<Events>
{events}
</Events>

<Categories>
early: Covers childhood, upbringing, family, education, and early influences that shaped the author.
personal: Focuses on relationships, friendships, family life, places of residence, and notable personal traits or beliefs.
career: Details their professional journey: first steps into writing, major publications, collaborations, recurring themes, style, and significant milestones.
legacy: Explains how their work was received, awards or recognition, cultural/literary impact, influence on other authors, and they are remembered today.
</Categories>


<Rules>
INCLUDE ALL THE INFORMATION FROM THE EVENTS, do not abbreviate or omit any information.
</Rules>
"""

EXTRACT_AND_CATEGORIZE_PROMPT = """
You are a Biographical Event Extractor and Categorizer. Your task is to analyze text chunks for events related to the life of the historical figure**

<Available Tools>
- `IrrelevantChunk` (use if the text contains NO biographical events relevant to the research question)
- `RelevantEventsCategorized` (use if the text contains relevant events - categorize them into the 4 categories)
</Available Tools>

<Categories>
early: Covers childhood, upbringing, family, education, and early influences that shaped the author.
personal: Focuses on relationships, friendships, family life, places of residence, and notable personal traits or beliefs.
career: Details their professional journey: first steps into writing, major publications, collaborations, recurring themes, style, and significant milestones.
legacy: Explains how their work was received, awards or recognition, cultural/literary impact, influence on other authors, and how they are remembered today.
</Categories>

**EXTRACTION RULES**:
- Extract COMPLETE sentences with ALL available details (dates, names, locations, context, emotions, motivations)
- Include surrounding context that makes the event meaningful and complete
- Preserve the original narrative flow and descriptive language
- Capture cause-and-effect relationships and consequences
- Include only events directly relevant to the research question
- Maintain chronological order within each category
- Format as clean bullet points with complete, detailed descriptions (e.g., "- In the spring of 1965, while living in a small apartment in Paris, she attended a poetry reading that fundamentally changed her approach to writing, inspiring her to experiment with free verse.")
- IMPORTANT: Return each category as a SINGLE string containing all bullet points, not as a list

<Text to Analyze>
{text_chunk}
</Text to Analyze>

You must call exactly one of the provided tools. Do not respond with plain text.
"""


MERGE_EVENTS_TEMPLATE = """You are a helpful assistant that will merge two lists of events: 
the original events (which must always remain) and new events (which may contain extra details). 
The new events should only be treated as additions if they provide relevant new information. 
The final output must preserve the original events and seamlessly add the new ones if applicable.

<Rules>
- Always include the original events exactly, do not omit or alter them.
- Add new events only if they are not duplicates, combining details if they overlap.
- Format the final list as bullet points, one event per line (e.g., "- Event details.").
- Keep the list clean, concise, and without commentary.
</Rules>

<Events>
Original events:
{original}

New events:
{new}
</Events>

<Output>
Return only the merged list of events as bullet points, nothing else.
</Output>"""
