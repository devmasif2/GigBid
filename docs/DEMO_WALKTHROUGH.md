# Three-minute demo walkthrough

## 0:00–0:25 — Start and orient

Start the local API and web app using [REVIEWER_GUIDE.md](./REVIEWER_GUIDE.md). Show the
Opportunity inbox and point out that listings are clearly marked synthetic. Complete onboarding
with a persona, hourly rate, and weekly Connects budget.

## 0:25–1:05 — Inspect a job and run analysis

Select the churn-classifier or similar sample job. Show the description, skills, budget,
screening question, warning signals, and Connects cost. Click **Run job analysis**. While the
stream runs, point out the analyst, risk, and fit progress chips and the trace identifier.
Explain that the branches are coordinated by the bid LangGraph rather than one opaque request.

## 1:05–1:50 — Review evidence and approval

Open the proposal review. Show the evidence IDs, exact-quote claim verification, critic feedback,
compliance verdict, dry-run action, price, and Connects preview. Edit the cover letter or a
screening answer, click **Save and recheck**, then show the validation result. Explain that
approval creates only an idempotent local draft; it does not submit a proposal or spend Connects.

## 1:50–2:20 — Conversation safety

Open Messages and choose a synthetic client message. Click **Draft reply for review**. Show the
SSE node progress, trace ID, editable reply field, and local approval controls. Emphasize that
client messages are untrusted and that approving this review never sends a message.

## 2:20–2:45 — Pipeline and analytics

Show the read-only simulator Pipeline and Analytics sections. Point out proposal stages,
simulated Connects, reply rate, and hire rate. Explain that these numbers are simulator metrics,
not live marketplace performance.

## 2:45–3:00 — Evidence and limitations

Briefly show `docs/GRAPHS.md`, `docs/TOOLS.md`, `docs/RND_REPORT.md`, and the generated evaluation
table. End by stating the key limitation: secure multi-user auth, live OAuth, distributed
workers, and public deployment are intentionally not claimed.
