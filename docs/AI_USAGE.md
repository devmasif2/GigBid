# AI Usage Disclosure

GigBid was developed with an AI coding assistant using the Copilot SDK in VS Code. Assistance
was used for repository exploration, implementation, test generation, documentation, and review.
The developer remains responsible for all code and manually validated the resulting behavior.

## Application AI boundaries

GigBid uses deterministic local workflow nodes and optional local retrieval components. It does
not send portfolio text, client messages, or job content to a hosted model by default. Optional
Ollama embeddings and a local cross-encoder are supported only for experiments.

- Retrieval variants V0, V1, V2, V3, and V8 are selectable evaluation components.
- Bid and conversation graphs coordinate risk, fit, drafting, verification, critique, compliance,
  and human approval.
- Exact-quote verification removes unsupported lines before critique; it is not semantic truth
  verification.
- Marketplace writes default to dry-run. The bid graph requires approval before creating a local
  draft, and conversation approval never sends a message.
- Provider cost, calibrated judge scores, and blind human ratings are marked `N/A` when
  unavailable rather than fabricated.

Job posts and client messages are untrusted. Only evidence marked `real` can reach the bid
approval gate. Browser sign-in and connection controls are demo state, not secure multi-user
authentication or real OAuth. Evaluation numbers are reproducible local measurements over
synthetic data; see [the evaluation README](../evals/README.md) and [data card](./DATA_CARD.md).

## Corrected assistant suggestion

An initial browser test asserted that a streamed draft appeared as visible paragraph text. The
application correctly renders the draft in an editable `textarea`, so the test was corrected to
assert the field value. This avoided weakening the UI behavior merely to satisfy the test.
