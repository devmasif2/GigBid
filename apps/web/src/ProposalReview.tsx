import { useCallback, useEffect, useState } from "react";

import { continueBid, getBidRun, reviewBid, type GraphRunResult } from "./lib/api";

function record(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

type Props = {
  threadId: string;
  revision: number;
  running: boolean;
  onForget: () => void;
};

export default function ProposalReview({ threadId, revision, running, onForget }: Props) {
  const [run, setRun] = useState<GraphRunResult>();
  const [draft, setDraft] = useState("");
  const [answers, setAnswers] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const applyRun = useCallback((result: GraphRunResult) => {
    setRun(result);
    const payload = record(result.interrupts[0]);
    const proposal = record(payload?.proposal_draft);
    if (typeof proposal?.cover_letter === "string") setDraft(proposal.cover_letter);
    if (Array.isArray(proposal?.screening_answers)) {
      setAnswers(proposal.screening_answers.map((answer: unknown) =>
        typeof answer === "string" ? answer : ""
      ));
    }
  }, []);

  const refresh = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      applyRun(await getBidRun(threadId));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not load the run.");
    } finally {
      setBusy(false);
    }
  }, [applyRun, threadId]);

  useEffect(() => {
    if (!running) void refresh();
  }, [refresh, revision, running]);

  async function submit(action: "approve" | "reject" | "edit") {
    setBusy(true);
    setError("");
    try {
      applyRun(await reviewBid(
        threadId, action, action === "edit" ? draft : undefined,
        action === "edit" ? answers : undefined,
      ));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Review failed.");
    } finally {
      setBusy(false);
    }
  }

  async function resumeRun() {
    setBusy(true);
    setError("");
    try {
      applyRun(await continueBid(threadId));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not continue the run.");
    } finally {
      setBusy(false);
    }
  }

  const payload = record(run?.interrupts[0]);
  const publication = record(run?.state.draft_publication);
  const publishedDraft = record(publication?.draft);
  const savedProposal = record(payload?.proposal_draft);
  const savedAnswers = Array.isArray(savedProposal?.screening_answers)
    ? savedProposal.screening_answers : [];
  const hasUnsavedChanges = (typeof savedProposal?.cover_letter === "string"
    && draft !== savedProposal.cover_letter)
    || JSON.stringify(answers) !== JSON.stringify(savedAnswers);
  const validation = record(payload?.edit_validation);
  const evidence = Array.isArray(payload?.evidence) ? payload.evidence : [];
  const preview = record(payload?.dry_run);
  const policy = record(payload?.marketplace_policy);
  const compliance = record(run?.state.compliance_verdict);
  const critique = record(run?.state.critique);
  const job = record(payload?.job);
  const questions = Array.isArray(job?.screening_questions) ? job.screening_questions : [];

  return (
    <section className="review-panel" aria-label="Proposal review" aria-live="polite">
      <h2>Proposal review</h2>
      <p className="muted">Local run {threadId}. No proposal is sent or Connects spent.</p>
      {error && <p className="error-text" role="alert">{error}</p>}
      {!run && (busy || running) && <p>Loading run…</p>}
      {run?.status === "running" && (
        <>
          <p>
            This run stopped before finishing, for example because the marketplace was
            unavailable after approval. Continue it once the service is back; completed steps
            and the saved draft are not repeated.
          </p>
          <button type="button" className="button button-dark" disabled={busy || running} onClick={() => void resumeRun()}>Continue run</button>
        </>
      )}
      {run?.status === "completed" && (
        <p>Run finished. Review status: {String(run.state.approval_status ?? run.state.decision ?? "completed")}.</p>
      )}
      {typeof run?.state.approval_error === "string" && (
        <p className="error-text" role="alert">{run.state.approval_error}</p>
      )}
      {run?.status === "completed" && compliance?.passed === false && (
        <p className="error-text" role="alert">
          Compliance blocked this draft: {Array.isArray(compliance.reasons) ? compliance.reasons.join("; ") : "See run details."}
        </p>
      )}
      {publication && (
        <p className="muted" role="status">
          {publication.outcome === "created" || publication.outcome === "already_exists"
            ? `Local draft ${String(publication.outcome === "created" ? "saved" : "already saved")} for job ${String(publishedDraft?.job_id ?? "")}. It is a draft only: it was not submitted and no Connects were spent.`
            : String(publication.reason ?? "No draft was created.")}
        </p>
      )}
      {run?.status === "interrupted" && payload && (
        <>
          <label className="review-label" htmlFor="proposal-draft">Proposal draft</label>
          <textarea id="proposal-draft" value={draft} onChange={(event) => setDraft(event.target.value)} />
          <p className="muted">Edit and recheck before approving; unsupported claims may be removed.</p>
          {questions.map((question, index) => (
            <div key={index}>
              <label className="review-label" htmlFor={`screening-answer-${index}`}>
                Screening question {index + 1}: {String(question)}
              </label>
              <textarea
                id={`screening-answer-${index}`}
                value={answers[index] ?? ""}
                maxLength={5000}
                onChange={(event) => setAnswers((current) =>
                  current.map((answer, answerIndex) => answerIndex === index ? event.target.value : answer)
                )}
              />
            </div>
          ))}
          {questions.length > 0 && (
            <p className="muted">Edited answers need an exact quoted evidence citation on its own line, like [evidence-id] "Evidence text". Verification is limited and still needs your review.</p>
          )}
          {validation && (
            <p className={validation.passed === true ? "muted" : "error-text"}>
              Edit validation: {validation.passed === true ? "passed" : "failed"}.{" "}
              {Array.isArray(validation.reasons) ? validation.reasons.join("; ") : ""}
            </p>
          )}
          <details>
            <summary>Evidence, risk, and review feedback</summary>
            {evidence.map((item, index) => {
              const entry = record(item);
              return <p key={String(entry?.id ?? index)}><strong>{String(entry?.id ?? "Evidence")}</strong>: {String(entry?.content ?? "")}</p>;
            })}
            <pre>{JSON.stringify({
              risk: payload.risk_report,
              claims: payload.claim_verification,
              critique,
              compliance,
            }, null, 2)}</pre>
          </details>
          <p className="muted">
            Dry-run preview: {String(preview?.action ?? "unavailable")}; price{" "}
            {String(preview?.price ?? "not provided")}; Connects{" "}
            {String(preview?.connects_cost ?? "not provided")}. No external action is taken.
          </p>
          <p className="muted">
            Policy source: {String(payload.marketplace_policy_source ?? "unavailable")}.
            {typeof policy?.version === "number" ? ` Version ${policy.version}.` : ""}
            {payload.marketplace_policy_source === "unavailable: local sample only"
              ? " Current marketplace rules are unavailable; this is only an illustrative local draft."
              : " Policy changes before publication require a new analysis."}
          </p>
          <div className="review-actions">
            <button type="button" className="button button-quiet" disabled={busy || !draft.trim()} onClick={() => void submit("edit")}>Save and recheck</button>
            <button type="button" className="button button-dark" disabled={busy || hasUnsavedChanges || validation?.passed === false} onClick={() => void submit("approve")}>Approve locally</button>
            <button type="button" className="button button-quiet" disabled={busy} onClick={() => void submit("reject")}>Reject</button>
          </div>
          <p className="muted">Approval reviews the saved draft; click “Save and recheck” before approving edits.</p>
        </>
      )}
      <div className="review-actions">
        <button type="button" className="text-button" disabled={busy || running} onClick={() => void refresh()}>Refresh run status</button>
        <button type="button" className="text-button" disabled={busy || running} onClick={onForget}>Forget this run on this device</button>
      </div>
    </section>
  );
}
