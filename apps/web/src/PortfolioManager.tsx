import { useState, type FormEvent } from "react";

import {
  deletePortfolioSource, listPortfolioSources, savePortfolioSource,
  type PortfolioEvidence, type PortfolioSource,
} from "./lib/api";

const types: PortfolioEvidence["type"][] = ["cv", "case_study", "repo_readme", "code", "review", "proposal"];

function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not read the file."));
    reader.onload = () => {
      if (typeof reader.result !== "string" || !reader.result.includes(",")) {
        reject(new Error("Could not encode the file."));
        return;
      }
      resolve(reader.result.slice(reader.result.indexOf(",") + 1));
    };
    reader.readAsDataURL(file);
  });
}

export default function PortfolioManager({ onChange }: { onChange: () => void }) {
  const [token, setToken] = useState("");
  const [sources, setSources] = useState<PortfolioSource[]>([]);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [editing, setEditing] = useState<PortfolioSource | null>(null);
  const [sourceId, setSourceId] = useState("");
  const [persona, setPersona] = useState("");
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<PortfolioEvidence["data_kind"]>("synthetic");
  const [evidenceType, setEvidenceType] = useState<PortfolioEvidence["type"]>("cv");
  const [skills, setSkills] = useState("");
  const [project, setProject] = useState("");
  const [date, setDate] = useState("");
  const [industry, setIndustry] = useState("");
  const [outcome, setOutcome] = useState("");
  const [attested, setAttested] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [fileKey, setFileKey] = useState(0);

  function clearForm() {
    setEditing(null); setSourceId(""); setPersona(""); setTitle(""); setKind("synthetic");
    setEvidenceType("cv"); setSkills(""); setProject(""); setDate(""); setIndustry("");
    setOutcome(""); setAttested(false); setFile(null); setFileKey((value) => value + 1);
  }

  async function refresh() {
    setBusy(true); setError(""); setMessage("");
    try {
      setSources(await listPortfolioSources(token));
      setConnected(true);
    } catch (failure) {
      setConnected(false);
      setSources([]);
      setError(failure instanceof Error ? failure.message : "Could not load portfolio sources.");
    } finally { setBusy(false); }
  }

  function edit(source: PortfolioSource) {
    setEditing(source); setSourceId(source.source_id); setPersona(source.freelancer_id);
    setTitle(source.title); setKind(source.data_kind); setEvidenceType(source.type);
    setSkills(source.skills.join(", ")); setProject(source.project ?? "");
    setDate(source.date ?? ""); setIndustry(source.client_industry ?? "");
    setOutcome(source.outcome ?? ""); setAttested(source.rights_attested);
    setFile(null); setFileKey((value) => value + 1); setError(""); setMessage("");
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || busy) return;
    if (file.size > 2_000_000) { setError("File exceeds the 2,000,000-byte limit."); return; }
    const parsedSkills = skills.split(",").map((skill) => skill.trim()).filter(Boolean);
    if (!parsedSkills.length) { setError("Enter at least one skill."); return; }
    setBusy(true); setError(""); setMessage("");
    try {
      const document = {
        source_id: sourceId.trim(), freelancer_id: persona.trim(), title: title.trim(),
        path: file.name, type: evidenceType, skills: parsedSkills, data_kind: kind,
        rights_attested: attested, project: project.trim() || null, date: date || null,
        client_industry: industry.trim() || null, outcome: outcome.trim() || null,
      };
      await savePortfolioSource(token, document, await readBase64(file), editing?.revision);
      onChange();
      clearForm();
      try {
        setSources(await listPortfolioSources(token));
        setMessage("Document saved and indexed.");
      } catch {
        setConnected(false);
        setError("Document was saved, but refreshing the source list failed. Reconnect to verify.");
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not save document.");
    } finally { setBusy(false); }
  }

  async function remove(source: PortfolioSource) {
    if (!window.confirm(`Delete "${source.title}" and its indexed chunks?`)) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await deletePortfolioSource(token, source);
      onChange();
      if (editing?.source_id === source.source_id && editing.freelancer_id === source.freelancer_id) clearForm();
      try {
        setSources(await listPortfolioSources(token));
        setMessage("Document and indexed chunks deleted.");
      } catch {
        setConnected(false);
        setError("Document was deleted, but refreshing the source list failed. Reconnect to verify.");
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not delete document.");
    } finally { setBusy(false); }
  }

  return (
    <div className="detail-section" aria-label="Local portfolio manager">
      <h3>Local document manager</h3>
      <p className="muted">
        Optional single-user local mode. Configure the SQLite index and management token on the API first.
        No public deployment or shared-machine protection is provided. Files are parsed locally; raw files
        are not retained. Extracted text and metadata are stored unencrypted.
      </p>
      <label className="review-label" htmlFor="portfolio-token">Local management token</label>
      <input id="portfolio-token" className="portfolio-input" type="password" autoComplete="off"
        value={token} onChange={(event) => { setToken(event.target.value); setConnected(false); setSources([]); clearForm(); }} />
      <div className="review-actions">
        <button type="button" className="button button-quiet" onClick={() => void refresh()} disabled={!token || busy}>
          {busy ? "Working…" : "Connect / refresh sources"}
        </button>
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      {message && <p className="muted" role="status">{message}</p>}
      {connected && (
        <>
          <p className="muted">{sources.length} managed sources. Updating requires selecting the file again.</p>
          {sources.map((source) => (
            <div className="signal-box portfolio-evidence" key={`${source.freelancer_id}:${source.source_id}`}>
              <strong>{source.title}</strong>
              <p>{source.freelancer_id} / {source.source_id} · {source.type} · {source.data_kind} · revision {source.revision}</p>
              <div className="review-actions">
                <button type="button" className="button button-quiet" disabled={busy} onClick={() => edit(source)}>Edit / replace</button>
                <button type="button" className="button button-quiet" disabled={busy} onClick={() => void remove(source)}>Delete</button>
              </div>
            </div>
          ))}
          <form onSubmit={(event) => void save(event)}>
            <h3>{editing ? "Replace document" : "Add document"}</h3>
            <div className="portfolio-form">
              <label>Persona ID<input required maxLength={200} disabled={!!editing || busy} value={persona} onChange={(e) => setPersona(e.target.value)} /></label>
              <label>Source ID<input required maxLength={100} pattern="([a-zA-Z0-9._]|-)+" disabled={!!editing || busy} value={sourceId} onChange={(e) => setSourceId(e.target.value)} /></label>
              <label>Title<input required maxLength={300} disabled={busy} value={title} onChange={(e) => setTitle(e.target.value)} /></label>
              <label>Type<select value={evidenceType} disabled={busy} onChange={(e) => setEvidenceType(e.target.value as PortfolioEvidence["type"])}>{types.map((type) => <option key={type}>{type}</option>)}</select></label>
              <label>Skills (comma-separated)<input required disabled={busy} value={skills} onChange={(e) => setSkills(e.target.value)} /></label>
              <label>Project<input disabled={busy} value={project} onChange={(e) => setProject(e.target.value)} /></label>
              <label>Date<input type="date" disabled={busy} value={date} onChange={(e) => setDate(e.target.value)} /></label>
              <label>Client industry<input disabled={busy} value={industry} onChange={(e) => setIndustry(e.target.value)} /></label>
              <label>Outcome<input disabled={busy} value={outcome} onChange={(e) => setOutcome(e.target.value)} /></label>
              <label>Evidence label<select value={kind} disabled={busy} onChange={(e) => { setKind(e.target.value as PortfolioEvidence["data_kind"]); setAttested(false); }}><option value="synthetic">Synthetic</option><option value="unverified">Unverified</option><option value="real">Real</option></select></label>
              <label>Document (.md, .txt, .pdf)<input key={fileKey} required type="file" accept=".md,.txt,.pdf" disabled={busy} onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
            </div>
            {kind === "real" && (
              <label><input required type="checkbox" checked={attested} disabled={busy} onChange={(e) => setAttested(e.target.checked)} /> I attest this material is real and I have permission to process it.</label>
            )}
            <p className="muted">Attestation is not independent verification. Review extracted PDF text for omissions and ordering.</p>
            <div className="review-actions">
              <button type="submit" className="button button-dark" disabled={busy}>{editing ? "Replace and reindex" : "Add and index"}</button>
              {editing && <button type="button" className="button button-quiet" disabled={busy} onClick={clearForm}>Cancel edit</button>}
            </div>
          </form>
        </>
      )}
    </div>
  );
}
