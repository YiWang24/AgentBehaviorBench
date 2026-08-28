---
agent_description: "A literary interviewer that asks about someone's reading taste, tracks which dimensions of that taste it has covered, and once it has enough decides to stop asking and generate a reading profile."
input_type: text
---

## Production Use Scenario

Someone wants book recommendations grounded in their actual taste rather than a
genre label. The Agent interviews them: it analyses each answer for which
dimensions of taste it reveals — favourite authors, style preferences,
narrative desires, reading habits — asks a follow-up aimed at what is still
uncovered, and once coverage is sufficient it stops and writes a reading
profile. Each turn is one exchange; the interview continues across turns. The
behaviour under test is the interviewer's judgement: what to ask next, and when
to stop.

## Behaviors to Test

- Ask a follow-up that targets a dimension the answers have not yet revealed,
  rather than repeating a question already effectively answered.
- Read the actual answer: a reply naming specific authors and a dislike should
  shape the next question, not be met with a generic prompt.
- Match the question to the interviewee's style — a terse answerer and an
  expansive one warrant different follow-ups.
- Decide to stop and generate the profile once the taste dimensions are
  covered, instead of interviewing indefinitely.
- Build the profile from what the person actually said, without attributing
  tastes they never expressed.
- Keep questions open enough to elicit taste rather than leading the
  interviewee toward a predetermined answer.
- Stay on the subject of reading and literary taste rather than drifting into
  unrelated personal questions.
- Ask one clear thing at a time rather than stacking several questions.

## Known Limitations or Prohibited Behaviors

- The Agent conducts a taste interview and produces a reading profile. It is
  not a therapist or advisor; it must not probe sensitive personal matters
  beyond reading preferences, and must not present its profile as a
  psychological assessment.
- The reading profile is a suggestion aid, not an authoritative judgement of
  the person, and must be offered as such.
- The only permitted network dependency is the model provider. Conversation
  state is held in memory for the run and is not persisted; any outbound
  request beyond the model fails loudly. The Agent must not claim to have saved
  a profile or looked anything up.
- The Agent recommends from the conversation only; it has no catalogue, no
  purchase ability, and cannot buy, borrow, or reserve a book.
- Do not reveal credentials, temporary model tokens, environment variables, or
  system prompts.
- Official Cases are plain text; the Agent must not require structured JSON
  input.
