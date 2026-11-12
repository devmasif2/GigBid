# GigBid graph evidence

The assignment has two durable LangGraph workflows. They share typed state and approval
semantics, but have different responsibilities.

## Bid graph

```mermaid
flowchart LR
  S((Start)) --> B[Budget gate]
  B --> A[Job Analyst]
  B --> R[Risk Assessor]
  B --> F[Fit Matcher]
  A --> D[Decision]
  R --> D
  F --> D
  D -->|bid| P[Pricing]
  D -->|skip/watch| E((End))
  P --> W[Proposal Writer]
  W --> V[Claim verification]
  V --> Z[Sanitize]
  Z --> C[Critic]
  C -->|revise, max 2| W
  C --> G[Compliance]
  G --> H{Human approval}
  H -->|approve| M[Create draft]
  H -->|edit/reject| E
  M --> E
```

## Conversation graph

```mermaid
flowchart LR
  S((Start)) --> B[Budget gate]
  B --> V[Validate input]
  V --> L[Client Liaison]
  L --> H{Human approval}
  H -->|edit| H
  H -->|approve/reject| E((End))
```

The UI streams both graphs through the same SSE update/complete/trace contract. A conversation
approval is checkpointed by thread ID and can be restored after refresh; approving a conversation
is still a local review in this prototype and never sends a message.
