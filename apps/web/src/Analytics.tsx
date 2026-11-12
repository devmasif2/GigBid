import { useCallback, useEffect, useState } from "react";

import { getPipeline, type PipelineSnapshot } from "./lib/api";

export default function Analytics() {
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
      setError(failure instanceof Error ? failure.message : "Analytics are unavailable.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const proposals = snapshot?.proposals ?? [];
  const hired = proposals.filter((proposal) => proposal.status === "hired").length;
  const replied = proposals.filter((proposal) =>
    ["replied", "interview", "hired"].includes(proposal.status),
  ).length;
  const replyRate = proposals.length ? Math.round((replied / proposals.length) * 100) : 0;
  const hireRate = proposals.length ? Math.round((hired / proposals.length) * 100) : 0;

  return (
    <section className="review-panel" id="analytics" aria-label="Analytics">
      <h2>Analytics</h2>
      <p className="muted">
        Read-only metrics from the local simulator pipeline. These are synthetic outcomes, not
        production marketplace performance.
      </p>
      <button type="button" className="button button-quiet" disabled={loading} onClick={() => void refresh()}>
        {loading ? "Loading analytics…" : "Refresh analytics"}
      </button>
      {error && <p className="error-text" role="alert">{error}</p>}
      {snapshot && !loading && (
        <div className="settings-facts" aria-label="Pipeline metrics">
          <div><span>Tracked proposals</span><strong>{proposals.length}</strong></div>
          <div><span>Reply rate</span><strong>{replyRate}%</strong></div>
          <div><span>Hire rate</span><strong>{hireRate}%</strong></div>
          <div><span>Simulated Connects remaining</span><strong>{snapshot.connects_balance}</strong></div>
        </div>
      )}
      {snapshot && !loading && proposals.length === 0 && (
        <p className="muted">No simulator proposals yet; metrics will appear after a local draft exists.</p>
      )}
    </section>
  );
}
