import { expect, test } from "@playwright/test";

const job = {
  job_id: "sample-job-001",
  title: "Build a customer churn prediction baseline",
  description: "Create a reproducible Python baseline and report precision and recall.",
  required_skills: ["Python", "classification"],
  budget: { min: 250, max: 450, currency: "USD" },
  duration_days: 14,
  screening_questions: [],
  warning_signals: [],
  connects_cost: 8,
  client_id: "client-001",
  posted_at_hour: 10,
  category: "machine_learning",
  data_kind: "synthetic",
};

const proposalPayload = (coverLetter: string, editValidation?: Record<string, unknown>) => ({
  job,
  proposal_draft: {
    cover_letter: coverLetter,
    screening_answers: [],
    evidence_ids: ["case-1"],
  },
  evidence: [{ id: "case-1", content: "Built a Python classification baseline." }],
  risk_report: { score: 0.1, flags: [] },
  claim_verification: [{ claim: "Built a Python classification baseline.", status: "supported" }],
  dry_run: { action: "create_proposal_draft", price: 350, connects_cost: 8, external_action_taken: false },
  ...(editValidation && { edit_validation: editValidation }),
});

function interruptedRun(coverLetter = '[case-1] "Built a Python classification baseline."') {
  return {
    status: "interrupted",
    state: { compliance_verdict: { passed: true, reasons: [] } },
    interrupts: [proposalPayload(coverLetter)],
  };
}

test("loads the inbox and shows a selected job", async ({ page }) => {
  await page.route("**/api/jobs*", async (route) => {
    await route.fulfill({ json: [job] });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Opportunity inbox" })).toBeVisible();
  const listing = page.getByRole("button", { name: /Build a customer churn prediction baseline/ });
  await expect(listing).toBeVisible();
  await listing.click();
  await expect(page.getByRole("region", { name: "Selected job details" })
    .getByRole("heading", { name: job.title })).toBeVisible();
  await expect(page.getByRole("button", { name: /Run job analysis/ })).toBeVisible();
});

test("shows read-only simulator analytics", async ({ page }) => {
  await page.route("**/api/jobs*", async (route) => {
    await route.fulfill({ json: [job] });
  });
  await page.route("**/api/pipeline", async (route) => {
    await route.fulfill({
      json: {
        connects_balance: 42,
        proposals: [
          { proposal_id: "proposal-1", job_id: job.job_id, status: "hired", price: 350,
            connects_spent: 8, created_at_hour: 1, updated_at_hour: 2 },
          { proposal_id: "proposal-2", job_id: job.job_id, status: "draft", price: 300,
            connects_spent: 0, created_at_hour: 3, updated_at_hour: 3 },
        ],
      },
    });
  });
  await page.goto("/");
  const analytics = page.getByRole("region", { name: "Analytics" });
  await expect(analytics).toContainText("Tracked proposals2");
  await expect(analytics).toContainText("Reply rate50%");
  await expect(analytics).toContainText("Hire rate50%");
  await expect(analytics).toContainText("42");
});

test("completes local onboarding and shows saved workspace preferences", async ({ page }) => {
  await page.route("**/api/jobs*", async (route) => {
    await route.fulfill({ json: [job] });
  });

  await page.goto("/");
  const onboarding = page.getByRole("region", { name: "Workspace onboarding" });
  await onboarding.getByLabel("Profile name").fill("Demo freelancer");
  await onboarding.getByLabel("Profile persona").selectOption("full_stack");
  await onboarding.getByLabel("Hourly rate").fill("75");
  await onboarding.getByLabel("Weekly Connects budget").fill("40");
  await onboarding.getByRole("button", { name: "Complete setup" }).click();
  await expect(onboarding).toContainText("Welcome back, Demo freelancer");
  const settings = page.getByRole("region", { name: "Settings" });
  await expect(settings).toContainText("full_stack");
  await expect(settings).toContainText("$75/hr");
  await expect(settings).toContainText("40 Connects");
});

test("signs in and connects the local marketplace and portfolio", async ({ page }) => {
  await page.route("**/api/jobs*", async (route) => {
    await route.fulfill({ json: [job] });
  });
  await page.goto("/");
  const account = page.getByRole("region", { name: "Sign in and connections" });
  await account.getByLabel("Account name").fill("Reviewer");
  await account.getByLabel("Account email").fill("reviewer@example.test");
  await account.getByRole("button", { name: "Sign in" }).click();
  await account.getByRole("button", { name: "Connect GigSim" }).click();
  await account.getByRole("button", { name: "Connect portfolio" }).click();
  await expect(account).toContainText("Signed in as reviewer@example.test");
  await expect(account).toContainText("GigSim connected");
  await expect(account).toContainText("Portfolio connected");
});

test("streams a conversation reply into the approval review", async ({ page }) => {
  await page.route("**/api/jobs*", async (route) => {
    await route.fulfill({ json: [job] });
  });
  await page.route("**/api/messages", async (route) => {
    await route.fulfill({
      json: [{
        message_id: "message-1",
        proposal_id: "proposal-1",
        job_id: job.job_id,
        sender: "client",
        body: "Can you clarify the first milestone?",
        sent_at_hour: 2,
      }],
    });
  });
  await page.route("**/api/graphs/conversation/stream", async (route) => {
    const interrupt = {
      conversation_id: "proposal-1",
      draft: { message: "I can clarify the first milestone and validation plan.", intent: "question", risk_flags: [] },
      external_action_taken: false,
    };
    await route.fulfill({
      contentType: "text/event-stream",
      body: [
        'event: update\ndata: {"client_liaison":{"conversation_draft":' +
          JSON.stringify(interrupt.draft) + "}}\n\n",
        `event: update\ndata: ${JSON.stringify({ __interrupt__: [interrupt] })}\n\n`,
        'event: complete\ndata: {"status":"interrupted"}\n\n',
        'event: trace\ndata: {"trace_id":"trace-conversation-1"}\n\n',
      ].join(""),
    });
  });
  await page.goto("/");
  const messages = page.getByRole("region", { name: "Simulator messages" });
  await messages.getByRole("button", { name: "Draft reply for review" }).click();
  await expect(messages).toContainText("client liaison");
  await expect(messages.getByLabel("Reply draft")).toHaveValue("I can clarify the first milestone and validation plan.");
  await expect(messages).toContainText("trace-conversation-1");
});

test("supports local proposal edit, recheck, and approval", async ({ page }) => {
  let coverLetter = '[case-1] "Built a Python classification baseline."';
  await page.route("**/api/jobs*", async (route) => {
    await route.fulfill({ json: [job] });
  });
  await page.route("**/api/pipeline", async (route) => {
    await route.fulfill({ json: { connects_balance: 100, proposals: [] } });
  });
  await page.route("**/api/messages", async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route("**/api/graphs/bid/review-thread", async (route) => {
    await route.fulfill({ json: interruptedRun(coverLetter) });
  });
  await page.route("**/api/graphs/bid/review-thread/approval", async (route) => {
    const body = JSON.parse(await route.request().postData() ?? "{}") as { action?: string; cover_letter?: string };
    if (body.action === "edit") {
      coverLetter = body.cover_letter ?? coverLetter;
      await route.fulfill({
        json: {
          ...interruptedRun(coverLetter),
          interrupts: [proposalPayload(coverLetter, { passed: true, reasons: [] })],
        },
      });
      return;
    }
    await route.fulfill({
      json: {
        status: "completed",
        state: {
          approval_status: "approved",
          draft_publication: {
            outcome: "created",
            draft: { job_id: job.job_id },
          },
        },
        interrupts: [],
      },
    });
  });
  await page.addInitScript(() => window.localStorage.setItem("gigbid.lastBidThread", "review-thread"));
  await page.goto("/");

  const review = page.getByRole("region", { name: "Proposal review" });
  await expect(review.getByRole("heading", { name: "Proposal review" })).toBeVisible();
  await expect(review.getByText("Dry-run preview: create_proposal_draft")).toBeVisible();
  await review.locator("summary").click();
  await expect(review.getByText(/case-1: Built a Python classification baseline\./)).toBeVisible();
  const draft = review.locator("#proposal-draft");
  await draft.fill("I have ten years of experience.");
  await review.getByRole("button", { name: "Save and recheck" }).click();
  await expect(review.getByText("Edit validation: passed.")).toBeVisible();
  await review.getByRole("button", { name: "Approve locally" }).click();
  await expect(review).toContainText("Local draft saved");
  await expect(review).toContainText("not submitted");
});

test("supports rejecting a proposal locally", async ({ page }) => {
  await page.route("**/api/jobs*", async (route) => {
    await route.fulfill({ json: [job] });
  });
  await page.route("**/api/pipeline", async (route) => {
    await route.fulfill({ json: { connects_balance: 100, proposals: [] } });
  });
  await page.route("**/api/messages", async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route("**/api/graphs/bid/reject-thread", async (route) => {
    await route.fulfill({ json: interruptedRun() });
  });
  await page.route("**/api/graphs/bid/reject-thread/approval", async (route) => {
    await route.fulfill({
      json: { status: "completed", state: { approval_status: "rejected" }, interrupts: [] },
    });
  });
  await page.addInitScript(() => window.localStorage.setItem("gigbid.lastBidThread", "reject-thread"));
  await page.goto("/");

  const review = page.getByRole("region", { name: "Proposal review" });
  await expect(review.getByRole("button", { name: "Reject" })).toBeVisible();
  await review.getByRole("button", { name: "Reject" }).click();
  await expect(review).toContainText("Review status: rejected");
});

test("shows an explicit marketplace outage state", async ({ page }) => {
  await page.route("**/api/jobs*", async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: '{"detail":"sample unavailable"}',
    });
  });
  await page.goto("/");
  const listings = page.getByRole("region", { name: "Job listings" });
  await expect(listings.getByRole("alert")).toContainText("Marketplace unavailable");
  await expect(listings.getByRole("button", { name: "Try again" })).toBeVisible();
});
