import { useEffect, useState } from "react";

const money = (v) => (v == null ? "" : v.toLocaleString("en-US", { style: "currency", currency: "USD" }));

export default function App() {
  const [corpora, setCorpora] = useState([]);
  const [corpus, setCorpus] = useState("parcel_invoices");
  const [files, setFiles] = useState([]);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("all");
  const [open, setOpen] = useState(null);

  useEffect(() => {
    fetch("/corpora").then((r) => r.json()).then(setCorpora).catch(() => setError("API not reachable on :8000"));
  }, []);

  async function run(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    const body = new FormData();
    body.append("corpus", corpus);
    for (const f of files) body.append("files", f);
    try {
      const r = await fetch("/audit", { method: "POST", body });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || r.statusText);
      setResult(j);
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  const shown = (result?.findings || []).filter((f) => filter === "all" || f.classification === filter);
  const recoverable = (result?.findings || [])
    .filter((f) => f.classification === "verifiable")
    .reduce((s, f) => s + (f.amount_usd || 0), 0);

  return (
    <main>
      <header>
        <h1>Sightline</h1>
        <p className="sub">Code computes, AI explains. Every finding cites its file and row or page.</p>
      </header>

      <form onSubmit={run} className="card">
        <label>
          Corpus
          <select value={corpus} onChange={(e) => setCorpus(e.target.value)}>
            {corpora.map((c) => (
              <option key={c.name} value={c.name}>{c.title}</option>
            ))}
          </select>
        </label>
        <label>
          Files <span className="hint">(leave empty to audit the bundled synthetic sample)</span>
          <input type="file" multiple onChange={(e) => setFiles([...e.target.files])} />
        </label>
        <button disabled={busy}>{busy ? "Auditing..." : "Run audit"}</button>
        {error && <p className="error">{error}</p>}
      </form>

      {result && (
        <>
          <section className="stats">
            <div><b>{result.findings.length}</b> findings</div>
            <div><b>{money(recoverable)}</b> verifiable impact</div>
            <div><b>{result.rejected_mappings.length}</b> rejected mappings</div>
            <div><b>{result.llm_cost_usd == null ? "n/a" : money(result.llm_cost_usd)}</b> LLM cost</div>
          </section>
          <div className="tabs">
            {["all", "verifiable", "judgment_required"].map((k) => (
              <button key={k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>{k.replace("_", " ")}</button>
            ))}
          </div>
          <ul className="findings">
            {shown.map((f) => (
              <li key={f.id} className={`card ${f.classification}`}>
                <div className="row" onClick={() => setOpen(open === f.id ? null : f.id)}>
                  <span className="id">{f.id}</span>
                  <span className="title">{f.title}</span>
                  <span className={`badge ${f.classification}`}>{f.classification.replace("_", " ")}</span>
                  <span className="amt">{money(f.amount_usd)}</span>
                </div>
                <p>{f.explanation}</p>
                {open === f.id && (
                  <div className="detail">
                    <h4>Citations</h4>
                    <ul>
                      {f.citations.map((c, i) => (
                        <li key={i}><code>{c.file}</code> · {c.location}<br /><small>{c.snippet}</small></li>
                      ))}
                    </ul>
                    <h4>Dispute note</h4>
                    <p className="note">{f.dispute_note}</p>
                    <small>explained by: {f.explained_by}</small>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </main>
  );
}
