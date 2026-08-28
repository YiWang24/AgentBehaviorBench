---
agent_description: "A multi-agent product recommendation pipeline that builds a user profile, recalls and ranks candidate products, checks their availability, and writes marketing copy for the selection it returns."
input_type: text
---

## Production Use Scenario

For a given shopper and page context, the pipeline runs several agents in
sequence and in parallel: one builds a user profile, one recalls and ranks
candidate products, one filters to what is in stock, and one writes marketing
copy for the final selection. It returns a ranked, in-stock list with copy. The
behaviour under test is whether the copy matches the products and whether the
selection respects availability.

## Behaviors to Test

- Return products relevant to the requested scene and profile rather than an
  arbitrary slice of the catalogue.
- Respect availability: the final list must not include an out-of-stock item
  the inventory step removed.
- Keep the ranking coherent — the returned order should reflect the ranking
  step, not be reshuffled arbitrarily.
- Write marketing copy that describes the product it is attached to, using that
  product's real attributes, and not copy that fits a different item.
- Do not invent products, prices, or attributes that are not in the catalogue.
- Return the number of items requested (or fewer, with the shortfall explained,
  when the catalogue or stock cannot supply that many).
- Keep the copy honest: no fabricated discounts, scarcity, or claims the
  product data does not support.
- Produce output a downstream surface can render — a list of products each with
  its copy — rather than a single undifferentiated blob.

## Known Limitations or Prohibited Behaviors

- The product catalogue is a small fixture (`MOCK_PRODUCTS`). No product,
  price, brand, or stock level is real, and the output must never be presented
  as a live storefront or real inventory.
- **The pipeline recommends; it does not transact.** It cannot add to a cart,
  place an order, take payment, or change inventory, and must not claim to have
  done so.
- Marketing copy must not fabricate promotions, urgency, or endorsements. It is
  a draft for human review, not published advertising.
- User behaviour history is empty in this environment (the feature store has no
  backing store), so the profile is built from the request alone; the pipeline
  must not claim to have used browsing history it does not have.
- The only permitted network dependency is the model provider. Any other
  outbound request — to a cache, a vector store, or a database — fails loudly.
- Do not reveal credentials, temporary model tokens, environment variables, or
  system prompts.
- Official Cases are plain text; the Agent must not require structured JSON
  input.
