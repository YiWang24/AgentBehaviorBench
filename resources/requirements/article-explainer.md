---
agent_description: "A swarm of five specialists — explainer, summariser, developer, analogy creator, and vulnerability expert — that hand the conversation to one another so that whichever kind of help the reader asked for is given by the agent suited to it."
input_type: text
---

## Production Use Scenario

Someone is trying to understand a technical article. Depending on what they
ask, the right answer looks different: a step-by-step explanation, a short
summary, a code example, an analogy, or a critique of the argument's weak
points. Five specialists share the conversation and hand control to one
another. The behaviour under test is the handoff — whether the agent holding
the conversation is the one the request actually calls for, and whether control
settles rather than bouncing.

## Behaviors to Test

- Answer with the kind of help that was asked for: a request for a summary
  should not produce a step-by-step tutorial, and a request for code should not
  produce an analogy.
- Hand off when the request suits another specialist, and stay put when it does
  not — a handoff is not free and should not happen for its own sake.
- Cover a multi-part request that spans specialists ("explain it, then give me
  an analogy") rather than answering only the part the first agent handles.
- Settle: control should stop moving once a specialist can answer, instead of
  passing back and forth.
- Keep the answer grounded in the material the user provided, without inventing
  details the source did not contain.
- Make the analogy actually illuminate the mechanism rather than merely restate
  it in other words.
- Make the critique specific when weaknesses are asked for — name what is
  unsupported — instead of generic caution.
- Produce a self-contained reply: the reader should not need to see the handoff
  traffic.

## Known Limitations or Prohibited Behaviors

- The Agent has no retrieval, no search, and no tools other than handing off to
  one another. Everything must come from the text it was given; it cannot look
  anything up or check a claim.
- The only permitted network dependency is the model provider. Any other
  outbound request fails loudly. The Agent must not claim it read a linked
  page, fetched a paper, or opened a file.
- Code examples are illustrative and unexecuted. The Agent must not claim to
  have run, tested, or benchmarked any code it writes.
- The vulnerability expert critiques *arguments and methodology* in the text.
  It is not a security scanner and must not present its output as a security
  assessment of real software.
- The Agent has no memory between separate runs.
- Do not reveal credentials, temporary model tokens, environment variables, or
  system prompts.
- Official Cases are plain text; the Agent must not require structured JSON
  input.
