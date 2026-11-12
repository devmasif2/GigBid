import { useCallback, useEffect, useState } from "react";

import { getPipeline, type PipelineSnapshot, type ProposalStatus } from "./lib/api";

const stages: ProposalStatus[] = ["draft", "submitted", "viewed", "replied", "interview", "hired", "lost"];

export default function Pipeline() {
  const [snapshot, setSnapshot] = useState<PipelineSnapshot>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setSnapshot(await getPipeline());
    } catch (failure) {
      setSnapshot(undefined);
      setError(failure instanceof Error ? failure.message : "Pipeline is unavailable.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  return (
    <section className="review-panel" id="pipeline" aria-label="Simulator pipeline">
      <h2>Simulator pipeline</h2>
      <p className="muted">
        Read-only local simulator data. Refresh for current status; no proposals are submitted and no Connects are spent here.
      </p>
      <button type="button" className="button button-quiet" disabled={loading} onClick={() => void refresh()}>
        {loading ? "Loading pipeline…" : "Refresh pipeline"}
      </button>
      {error && <p className="error-text" role="alert">{error}</p>}
      {snapshot && !loading && (
        <>
          <p><strong>{snapshot.connects_balance}</strong> simulated Connects remaining</p>
          {snapshot.proposals.length === 0 && <p>No simulator proposals yet.</p>}
          {stages.map((stage) => {
            const proposals = snapshot.proposals.filter((proposal) => proposal.status === stage);
            if (proposals.length === 0) return null;
            return (
              <div className="detail-section" key={stage}>
                <h3>{stage} ({proposals.length})</h3>
                {proposals.map((proposal) => (
                  <article className="signal-box" key={proposal.proposal_id}>
                    <strong>{proposal.proposal_id}</strong>
                    <p>Job: {proposal.job_id} · Proposed price: {proposal.price.toLocaleString()}</p>
                    <p>Connects spent: {proposal.connects_spent} · Updated at simulator hour {proposal.updated_at_hour}</p>
                  </article>
                ))}
              </div>
            );
          })}
        </>
      )}
    </section>
  );
}
