import { FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorBox, PageChip, SourceViewer, Spinner } from "../components";

/** Server snippets mark matches with <mark>; render only that tag. */
function Snippet({ html }: { html: string }) {
  return <>{html.split(/(<mark>.*?<\/mark>)/g).map((p, i) => p.startsWith("<mark>") ? <mark key={i}>{p.slice(6, -7)}</mark> : <span key={i}>{p}</span>)}</>;
}

export default function Search() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  const [viewer, setViewer] = useState<{ book: string; page: number } | null>(null);
  const search = async (term: string) => {
    if (term.trim().length < 2) return;
    setBusy(true); setErr(null);
    try { setRes(await api(`/search?q=${encodeURIComponent(term)}`)); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const run = (e?: FormEvent) => { e?.preventDefault(); if (q === params.get("q")) search(q); else setParams({ q }); };
  // The URL is the source of truth, so links like /search?q=... (top bar, back button, shared) run the search.
  const urlQ = params.get("q") ?? "";
  useEffect(() => { setQ(urlQ); search(urlQ); }, [urlQ]);
  const total = res ? res.books.length + res.passages.length + res.notes.length + res.cards.length : 0;
  return (
    <div className="page-narrow stack gap-24">
      <h1>Search</h1>
      <form className="row gap-8" onSubmit={run}>
        <input className="input" autoFocus placeholder="Search your books, notes and flashcards" aria-label="Search" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn btn-strong" disabled={busy}>{busy ? <Spinner /> : "Search"}</button>
      </form>
      {err && <ErrorBox error={err} />}
      {res && total === 0 && <div className="card empty"><h3>No matches for “{q}”</h3><span className="muted">Try a different word, or check spelling.</span></div>}
      {res?.books.length > 0 && <section className="stack gap-8"><span className="label">Books</span>{res.books.map((b: any) => <Link key={b.id} to={`/books/${b.id}`} className="card-sm">{b.title}</Link>)}</section>}
      {res?.passages.length > 0 && <section className="stack gap-8"><span className="label">In your books</span>
        {res.passages.map((p: any, i: number) => (
          <div key={i} className="card-sm stack gap-8"><div className="row gap-8"><span className="small muted">{p.book}</span><PageChip page={p.pdf_page} label={p.page_label} onOpen={(pg) => setViewer({ book: p.book_id, page: pg })} /></div>
            <p className="reading" style={{ fontSize: 16 }}>…<Snippet html={p.snippet} />…</p></div>))}</section>}
      {res?.notes.length > 0 && <section className="stack gap-8"><span className="label">Notes</span>{res.notes.map((n: any) => <Link key={n.id} to={`/books/${n.book_id}/notes`} className="card-sm stack gap-4" style={{ color: "inherit", textDecoration: "none" }}><span className="small muted">{n.book}</span><span>{n.text || n.quote}</span></Link>)}</section>}
      {res?.cards.length > 0 && <section className="stack gap-8"><span className="label">Flashcards</span>{res.cards.map((c: any) => <div key={c.id} className="card-sm stack gap-4"><strong>{c.front}</strong><span className="small muted">{c.back}</span></div>)}</section>}
      {viewer && <SourceViewer bookId={viewer.book} page={viewer.page} onClose={() => setViewer(null)} />}
    </div>
  );
}
