import { useCallback, useEffect, useRef, useState } from "react";

import {
  getConversationRun, getMessages, reviewConversation, streamConversation,
  type GraphRunResult, type MarketplaceMessage,
} from "./lib/api";

const STORAGE_KEY = "gigbid.lastConversationThread";

function record(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown> : undefined;
}

export default function Messages() {
  const [messages, setMessages] = useState<MarketplaceMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [thread, setThread] = useState<string | null>(() => localStorage.getItem(STORAGE_KEY));
  const [run, setRun] = useState<GraphRunResult>();
  const [reply, setReply] = useState("");
  const [nodes, setNodes] = useState<string[]>([]);
  const locallyStartedThread = useRef<string | null>(null);

  const applyRun = useCallback((value: GraphRunResult) => {
    setRun(value);
    const draft = record(record(value.interrupts[0])?.draft);
    if (typeof draft?.message === "string") setReply(draft.message);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setMessages(await getMessages());
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Messages are unavailable.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!thread) return;
    if (locallyStartedThread.current === thread) {
      locallyStartedThread.current = null;
      return;
    }
    let active = true;
    getConversationRun(thread).then((value) => {
      if (active) applyRun(value);
    }).catch((failure: unknown) => {
      if (active) setError(failure instanceof Error ? failure.message : "Could not restore review.");
    });
    return () => { active = false; };
  }, [thread, applyRun]);

  async function draftReply(message: MarketplaceMessage) {
    setBusy(true);
    setError("");
    const id = crypto.randomUUID();
    try {
      setNodes([]);
      const result = await streamConversation(id, message, (names) => {
        setNodes((current) => [...current, ...names]);
      });
      localStorage.setItem(STORAGE_KEY, id);
      locallyStartedThread.current = id;
      setThread(id);
      applyRun(result);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not draft a reply.");
    } finally {
      setBusy(false);
    }
  }

  async function review(action: "approve" | "reject" | "edit") {
    if (!thread) return;
    setBusy(true);
    setError("");
    try {
      applyRun(await reviewConversation(thread, action, action === "edit" ? reply : undefined));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Review failed.");
    } finally {
      setBusy(false);
    }
  }

  const payload = record(run?.interrupts[0]);
  const draft = record(payload?.draft);
  const flags = Array.isArray(draft?.risk_flags) ? draft.risk_flags : [];
  const validation = record(payload?.edit_validation);
  const unsaved = typeof draft?.message === "string" && reply !== draft.message;
  const traceId = record(run?.state.observability)?.trace_id;

  return (
    <section className="review-panel" id="messages" aria-label="Simulator messages">
      <h2>Simulator messages</h2>
      <p className="muted">
        Local simulator only. Messages are untrusted; approval records a local review and never sends a reply.
      </p>
      {error && <p className="error-text" role="alert">{error}</p>}
      <button className="button button-quiet" type="button" disabled={loading} onClick={() => void refresh()}>
        {loading ? "Loading messages…" : "Refresh messages"}
      </button>
      {!loading && !error && messages.length === 0 && <p>No simulator messages yet.</p>}
      {thread && (
        <div className="signal-box" aria-live="polite">
          <strong>Reply review</strong>
          {nodes.length > 0 && (
            <div className="node-list" aria-label="Conversation run viewer">
              {nodes.map((node, index) => <span className="node-chip" key={`${node}-${index}`}>{node.replaceAll("_", " ")}</span>)}
            </div>
          )}
          {typeof traceId === "string" && (
            <p className="muted">Trace: {traceId}</p>
          )}
          {typeof run?.state.client_message === "string" && (
            <p style={{ whiteSpace: "pre-wrap" }}>Client message: {run.state.client_message}</p>
          )}
          {draft && (
            <>
              <p>Intent: {String(draft.intent ?? "unknown")}</p>
              {flags.length > 0 && <p className="error-text">Safety flags: {flags.join(", ")}</p>}
              <label className="review-label" htmlFor="conversation-reply">Reply draft</label>
              <textarea id="conversation-reply" value={reply} maxLength={5000}
                onChange={(event) => setReply(event.target.value)} />
              <p className="muted">Save and recheck edits before approval. Checks are limited; review all claims yourself.</p>
              {validation && (
                <p className={validation.passed === true ? "muted" : "error-text"}>
                  Edit validation: {validation.passed === true ? "passed" : "failed"}.{" "}
                  {Array.isArray(validation.reasons) ? validation.reasons.join("; ") : ""}
                </p>
              )}
              <p className="muted">No message will be sent, even if approved.</p>
            </>
          )}
          {run?.status === "interrupted" && (
            <div className="review-actions">
              <button type="button" className="button button-quiet" disabled={busy || !reply.trim()} onClick={() => void review("edit")}>Save and recheck</button>
              <button type="button" className="button button-dark" disabled={busy || unsaved || validation?.passed === false} onClick={() => void review("approve")}>Approve locally</button>
              <button type="button" className="button button-quiet" disabled={busy} onClick={() => void review("reject")}>Reject</button>
            </div>
          )}
          {run?.status === "completed" && <p>Local review: {String(run.state.approval_status ?? "completed")}. Nothing sent.</p>}
          {typeof run?.state.approval_error === "string" && <p className="error-text">{run.state.approval_error}</p>}
          <button type="button" className="text-button" disabled={busy} onClick={() => {
            localStorage.removeItem(STORAGE_KEY);
            setThread(null);
            setRun(undefined);
          }}>Forget this review on this device</button>
        </div>
      )}
      {messages.map((message) => (
        <article className="detail-section" key={message.message_id}>
          <strong>{message.sender === "client" ? "Client" : "You"} · {message.proposal_id} · hour {message.sent_at_hour}</strong>
          <p style={{ whiteSpace: "pre-wrap" }}>{message.body}</p>
          {message.sender === "client" && (
            <button type="button" className="button button-quiet" disabled={busy || thread !== null}
              onClick={() => void draftReply(message)}>Draft reply for review</button>
          )}
        </article>
      ))}
    </section>
  );
}
