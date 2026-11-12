import { useState, type FormEvent } from "react";

import { searchPortfolio, type PortfolioEvidence } from "./lib/api";

export default function Portfolio() {
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState("");
  const [items, setItems] = useState<PortfolioEvidence[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const term = query.trim();
    if (!term || loading) return;
    setLoading(true);
    setError("");
    setItems([]);
    setSearched("");
    try {
      setItems(await searchPortfolio(term));
      setSearched(term);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Portfolio search is unavailable.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="review-panel" id="portfolio" aria-label="Portfolio evidence">
      <h2>Portfolio evidence</h2>
      <p className="muted">
        Search the configured portfolio index. Results are unverified source material, not proof of
        authorship or claims. Real labels are operator declarations; synthetic evidence cannot support a real bid.
      </p>
      <form className="search-row" onSubmit={(event) => void search(event)}>
        <div className="search-box">
          <input
            aria-label="Search portfolio evidence"
            placeholder="Search a skill or requirement"
            maxLength={500}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <button className="button button-dark" type="submit" disabled={loading || !query.trim()}>
          {loading ? "Searching…" : "Search portfolio"}
        </button>
      </form>
      {error && <p className="error-text" role="alert">{error}</p>}
      {searched && (
        <p className="muted" role="status">
          {items.length ? `Up to five matches for “${searched}”.` : `No matches for “${searched}”.`}
        </p>
      )}
      {items.map((item) => (
        <article className="signal-box portfolio-evidence" key={item.id}>
          <strong>{item.title}</strong>
          <p>{item.type} · {item.data_kind} · Persona: {item.freelancer_id ?? "not specified"}</p>
          <p>Source: {item.source}</p>
          {item.project && <p>Project: {item.project}</p>}
          {item.date && <p>Date: {item.date}</p>}
          {item.client_industry && <p>Client industry: {item.client_industry}</p>}
          {item.outcome && <p>Outcome: {item.outcome}</p>}
          <p>Skills: {item.skills.join(", ") || "not specified"}</p>
          <pre>{item.content}</pre>
        </article>
      ))}
    </section>
  );
}
