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
