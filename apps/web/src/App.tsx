import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { getJobs, streamBidAnalysis, type GraphState, type SampleJob } from "./lib/api";
import ProposalReview from "./ProposalReview";
import Messages from "./Messages";
import Pipeline from "./Pipeline";

const RUN_STORAGE_KEY = "gigbid.lastBidThread";

type LoadState = "loading" | "ready" | "error";
type AnalysisState = {
  phase: "idle" | "running" | "completed" | "error";
  nodes: string[];
  state: GraphState;
  message?: string;
};

const emptyAnalysis: AnalysisState = { phase: "idle", nodes: [], state: {} };

function formatBudget(job: SampleJob): string {
  const { min, max, currency } = job.budget;
  return `${currency} ${min.toLocaleString()}–${max.toLocaleString()}`;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function displayScore(report: unknown): string {
  const score = asRecord(report)?.score;
  return typeof score === "number" ? `${Math.round(score * 100)}%` : "—";
}

export default function App() {
  const [jobs, setJobs] = useState<SampleJob[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [queryInput, setQueryInput] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [analysis, setAnalysis] = useState<AnalysisState>(emptyAnalysis);
  const [reviewThread, setReviewThread] = useState<string | null>(
    () => window.localStorage.getItem(RUN_STORAGE_KEY),
  );
  const [reviewRevision, setReviewRevision] = useState(0);

  const selectedJob = useMemo(
    () => jobs.find((job) => job.job_id === selectedId),
    [jobs, selectedId],
  );

  const loadJobs = useCallback(async (query: string) => {
    setLoadState("loading");
    setErrorMessage("");
    try {
      const result = await getJobs(query);
      setJobs(result);
      setSelectedId((current) =>
        current && result.some((job) => job.job_id === current)
          ? current
          : result[0]?.job_id,
      );
      setAnalysis(emptyAnalysis);
      setLoadState("ready");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not load opportunities.");
      setLoadState("error");
    }
  }, []);

  useEffect(() => {
    void loadJobs("");
  }, [loadJobs]);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setActiveQuery(queryInput.trim());
    void loadJobs(queryInput.trim());
  }

  async function analyzeJob() {
    if (!selectedJob || analysis.phase === "running" || reviewThread) return;
    const threadId = crypto.randomUUID();
    window.localStorage.setItem(RUN_STORAGE_KEY, threadId);
    setReviewThread(threadId);
    setAnalysis({ phase: "running", nodes: [], state: {} });
    try {
      const result = await streamBidAnalysis(selectedJob, threadId, (nodeNames, update) => {
        setAnalysis((current) => {
          const mergedState = { ...current.state };
          for (const value of Object.values(update)) {
            const nodeState = asRecord(value);
            if (nodeState) Object.assign(mergedState, nodeState);
          }
          return {
            ...current,
            nodes: [...current.nodes, ...nodeNames.filter((name) => name !== "__interrupt__")],
            state: mergedState,
          };
        });
      });
      setAnalysis((current) => ({
        ...current,
        phase: "completed",
        state: { ...current.state, ...result.state },
        message:
          result.status === "interrupted"
            ? "This run reached the approval gate; review its current status above."
            : undefined,
      }));
      setReviewRevision((current) => current + 1);
    } catch (error) {
      setAnalysis((current) => ({
        ...current,
        phase: "error",
        message: error instanceof Error ? error.message : "Analysis failed.",
      }));
      setReviewRevision((current) => current + 1);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="GigBid home">
          <span className="brand-mark">g</span>
          <span>gigbid<span className="brand-period">.</span></span>
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          <a className="nav-item active" href="#inbox" aria-current="page">
            <span className="nav-icon">▤</span> Opportunity inbox
            <span className="nav-count">{jobs.length}</span>
          </a>
          <span className="nav-item nav-disabled" title="Not implemented yet">
            <span className="nav-icon">▣</span> Proposal studio
          </span>
          <a className="nav-item" href="#pipeline">
            <span className="nav-icon">⇄</span> Pipeline
          </a>
          <a className="nav-item" href="#messages">
            <span className="nav-icon">☷</span> Messages
          </a>
          <span className="nav-item nav-disabled" title="Not implemented yet">
            <span className="nav-icon">◷</span> Agent runs
          </span>
        </nav>
        <div className="sidebar-bottom">
          <div className="connection-indicator"><span /> Local sample mode</div>
          <div className="sidebar-note">Only explicitly real portfolio evidence can support a bid.</div>
        </div>
      </aside>

      <main className="main-content" id="inbox">
        <header className="topbar">
          <div className="breadcrumb">Workspace <span>/</span> Opportunities</div>
          <div className="profile-chip"><span className="avatar">D</span><span>Demo workspace</span></div>
        </header>

        <section className="page-heading">
          <div>
            <div className="eyebrow">YOUR MARKETPLACE</div>
            <h1>Opportunity inbox</h1>
            <p>Review the fit and risk before deciding where to spend your time.</p>
          </div>
          <div className="sample-pill"><span /> SYNTHETIC SAMPLE DATA</div>
        </section>

        <div className="degraded-banner" role="status">
          <span className="banner-symbol">i</span>
          <span><strong>Local demo mode.</strong> These sample jobs are synthetic, not live marketplace listings.</span>
        </div>

        {reviewThread && (
          <ProposalReview
            threadId={reviewThread}
            revision={reviewRevision}
            running={analysis.phase === "running"}
            onForget={() => {
              window.localStorage.removeItem(RUN_STORAGE_KEY);
              setReviewThread(null);
            }}
          />
        )}

        <form className="search-row" onSubmit={submitSearch}>
          <div className="search-box">
            <span aria-hidden="true">⌕</span>
            <input
              aria-label="Search jobs"
              placeholder="Search title, description, or skills"
              value={queryInput}
              disabled={analysis.phase === "running"}
              onChange={(event) => setQueryInput(event.target.value)}
            />
            {queryInput && (
              <button
                type="button"
                className="clear-search"
                disabled={analysis.phase === "running"}
                aria-label="Clear search"
                onClick={() => {
                  setQueryInput("");
                  setActiveQuery("");
                  void loadJobs("");
                }}
              >×</button>
            )}
          </div>
          <button className="button button-dark" type="submit" disabled={analysis.phase === "running"}>Search</button>
          <button
            className="button button-quiet refresh-button"
            type="button"
            onClick={() => void loadJobs(activeQuery)}
            disabled={loadState === "loading" || analysis.phase === "running"}
          >↻ <span>Refresh</span></button>
        </form>

        <div className="inbox-layout">
          <section className="job-list" aria-label="Job listings">
            <div className="list-heading">
              <div><h2>Sample opportunities</h2><span>{jobs.length} local fixtures</span></div>
              <span className="sort-label">Local sample data</span>
            </div>
            {loadState === "loading" && (
              <div className="state-card" role="status"><span className="spinner" /> Loading sample jobs…</div>
            )}
            {loadState === "error" && (
              <div className="state-card error-card" role="alert">
                <strong>Marketplace unavailable</strong>
                <span>{errorMessage}</span>
                <button className="text-button" onClick={() => void loadJobs(activeQuery)}>Try again</button>
              </div>
            )}
            {loadState === "ready" && jobs.length === 0 && (
              <div className="state-card"><strong>No matching jobs</strong><span>Try a different title or skill.</span></div>
            )}
            {loadState === "ready" && jobs.map((job) => (
              <button
                className={`job-card${selectedId === job.job_id ? " selected" : ""}`}
                key={job.job_id}
                disabled={analysis.phase === "running"}
                onClick={() => {
                  setSelectedId(job.job_id);
                  setAnalysis(emptyAnalysis);
                }}
                aria-pressed={selectedId === job.job_id}
              >
                <div className="job-card-top">
                  <span className="client-avatar">{job.title.slice(0, 1).toUpperCase()}</span>
                  <span className="job-age">Sample listing</span>
                  <span className="sample-pill small">SAMPLE</span>
                </div>
                <h3>{job.title}</h3>
                <div className="job-meta">
                  <span>{formatBudget(job)}</span>
                  <span className="meta-dot">·</span>
                  <span>{job.duration_days ? `${job.duration_days} days` : "Duration not set"}</span>
                </div>
                <p className="job-summary">{job.description}</p>
                <div className="skill-list">
                  {job.required_skills.slice(0, 4).map((skill) => <span className="skill-tag" key={skill}>{skill}</span>)}
                </div>
                <div className="job-card-footer">
                  <span className="risk-tag">{job.warning_signals.length ? "Review risk signals" : "Risk not assessed"}</span>
                  <span>{job.connects_cost ?? "—"} Connects</span>
                </div>
              </button>
            ))}
          </section>

          <section className="detail-panel" aria-label="Selected job details">
            {selectedJob ? (
              <>
                <div className="detail-header">
                  <div className="detail-label">JOB OVERVIEW <span className="sample-pill small">SYNTHETIC</span></div>
                  <h2>{selectedJob.title}</h2>
                  <div className="detail-meta"><span>{formatBudget(selectedJob)}</span><span>·</span><span>{selectedJob.duration_days ?? "—"} days</span></div>
                </div>
                <div className="detail-section">
                  <h3>About the project</h3>
                  <p>{selectedJob.description}</p>
                </div>
                <div className="detail-section">
                  <h3>Required skills</h3>
                  <div className="skill-list detail-skills">
                    {selectedJob.required_skills.map((skill) => <span className="skill-tag" key={skill}>{skill}</span>)}
                  </div>
                </div>
                {selectedJob.warning_signals.length > 0 && (
                  <div className="signal-box">
                    <strong>Signals to review</strong>
                    <ul>{selectedJob.warning_signals.map((signal) => <li key={signal}>{signal.replaceAll("_", " ")}</li>)}</ul>
                  </div>
                )}
                {selectedJob.screening_questions.length > 0 && (
                  <div className="detail-section">
                    <h3>Screening question</h3>
                    {selectedJob.screening_questions.map((question) => <p className="question" key={question}>{question}</p>)}
                  </div>
                )}
                <div className="detail-facts">
                  <div><span>Base Connects (policy may adjust)</span><strong>{selectedJob.connects_cost ?? "Not provided"}</strong></div>
                  <div><span>Source</span><strong>Local sample fixture</strong></div>
                </div>
                <button
                  className="button button-accent analyze-button"
                  onClick={() => void analyzeJob()}
                  disabled={analysis.phase === "running" || reviewThread !== null}
                >
                  {analysis.phase === "running" ? <><span className="button-spinner" /> Analyzing…</> : "Run job analysis"}
                  {analysis.phase !== "running" && <span aria-hidden="true">→</span>}
                </button>
                {reviewThread && <p className="muted">Forget the tracked run above before starting another.</p>}

                {analysis.phase !== "idle" && (
                  <div className="analysis-panel" aria-live="polite">
                    <div className="analysis-title">
                      <h3>Agent analysis</h3>
                      <span className={`analysis-status ${analysis.phase}`}>{analysis.phase}</span>
                    </div>
                    {analysis.nodes.length > 0 && (
                      <div className="node-list">
                        {analysis.nodes.map((node, index) => <span className="node-chip" key={`${node}-${index}`}>{node.replaceAll("_", " ")}</span>)}
                      </div>
                    )}
                    {analysis.phase === "running" && <p className="muted">Streaming progress from the bid workflow…</p>}
                    {analysis.phase === "error" && <p className="error-text">{analysis.message}</p>}
                    {analysis.message && analysis.phase === "completed" && <p className="muted">{analysis.message}</p>}
                    {analysis.phase === "completed" && (
                      <>
                        <div className={`decision-card decision-${String(analysis.state.decision ?? "unknown")}`}>
                          <span>Recommendation</span>
                          <strong>{String(analysis.state.decision ?? "Completed")}</strong>
                          {typeof analysis.state.decision_reason === "string" && <p>{analysis.state.decision_reason}</p>}
                        </div>
                        <div className="score-row">
                          <div><span>Fit</span><strong>{displayScore(analysis.state.fit_report)}</strong></div>
                          <div><span>Risk</span><strong>{displayScore(analysis.state.risk_report)}</strong></div>
                        </div>
                        <p className="analysis-disclaimer">Analysis is a deterministic prototype. Synthetic portfolio evidence cannot justify a real proposal.</p>
                      </>
                    )}
                  </div>
                )}
              </>
            ) : (
              <div className="detail-empty"><span className="empty-icon">⌑</span><h2>Select an opportunity</h2><p>Choose a job from the inbox to review its details.</p></div>
            )}
          </section>
        </div>
        <Pipeline />
        <Messages />
        <footer className="page-footer"><span>GigBid · Human-approved freelancer copilot</span><span>Prototype · No messages or proposals are sent</span></footer>
      </main>
    </div>
  );
}
