import { FormEvent, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, download } from "../api";
import { ErrorBox, Loading, PageChip, SourceViewer } from "../components";
import { VoiceInput } from "../voice";
import { useApi } from "../state";

export default function Notes() {
  const { bookId } = useParams();
  const { data: book } = useApi<any>(`/books/${bookId}`);
  const { data: notes, error, reload } = useApi<any[]>(`/books/${bookId}/notes`);
  const [filter, setFilter] = useState<string>("all");
  const [tab, setTab] = useState<"all" | "note" | "highlight">("all");
  const [text, setText] = useState("");
  const [page, setPage] = useState("");
  const [viewer, setViewer] = useState<number | null>(null);
  const [err, setErr] = useState<any>(null);
  if (error) return <div className="page"><ErrorBox error={error} /></div>;
  if (!notes || !book) return <Loading />;
  const chapters = book.chapters.filter((c: any) => c.kind === "chapter" || c.kind === "appendix");
  const shown = notes.filter((n) => (filter === "all" || String(n.chapter_n) === filter) && (tab === "all" || n.kind === tab));
  const add = async (e: FormEvent) => {
    e.preventDefault(); setErr(null);
    try { await api(`/books/${bookId}/notes`, { body: { kind: "note", text, page_label: page.trim() || null } }); setText(""); setPage(""); reload(true); } catch (e) { setErr(e); }
  };
  const exportMd = () => {
    const md = `# Notes: ${book.title}\n\n` + notes.map((n) => `- ${n.page_label ? `(p. ${n.page_label}) ` : ""}${n.quote ? `“${n.quote}” ` : ""}${n.text ?? ""}`).join("\n");
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([md], { type: "text/markdown" })); a.download = "lectern-notes.md"; a.click();
  };
  return (
    <div className="page stack gap-24">
      <nav className="small muted"><Link to={`/books/${bookId}`}>{book.title}</Link> / Notes</nav>
      <div className="row between wrap gap-12"><h1>Notes</h1>
        <div className="row gap-8 wrap"><select className="select" style={{ height: 40, width: 200, maxWidth: "100%" }} aria-label="Chapter" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">All chapters</option>{chapters.map((c: any) => <option key={c.id} value={c.n}>Ch. {c.n}: {c.title.slice(0, 40)}</option>)}</select>
          <button className="btn btn-sm btn-secondary" onClick={exportMd} disabled={!notes.length}>Export</button>
          <button className="btn btn-sm btn-secondary" onClick={() => download("/me/cards.csv", "lectern-flashcards.csv")}>Flashcards CSV</button></div>
      </div>
      <div className="seg" role="tablist">{[["all", "All"], ["note", "Notes"], ["highlight", "Highlights"]].map(([v, l]) => <button key={v} role="tab" aria-checked={tab === v} onClick={() => setTab(v as any)}>{l}</button>)}</div>
      <form className="card row gap-8 wrap" onSubmit={add}>
        {err && <ErrorBox error={err} />}
        <input className="input grow" style={{ flexBasis: 300 }} placeholder="New note" aria-label="New note" value={text} onChange={(e) => setText(e.target.value)} maxLength={4000} />
        <VoiceInput compact onText={(t) => setText((prev) => (prev.trim() ? `${prev.trim()} ${t}` : t))} />
        <input className="input mono" style={{ width: 120 }} placeholder="Book page" aria-label="Book page (optional)" inputMode="numeric" value={page} onChange={(e) => setPage(e.target.value)} />
        <button className="btn btn-strong" disabled={!text.trim()}>Add</button>
      </form>
      {shown.length === 0 ? <div className="card empty"><h3>No notes yet</h3><span className="muted">Save pages from the source viewer, or add a note above.</span></div> :
        <div className="stack gap-12">{shown.map((n) => (
          <div key={n.id} className="card-sm stack gap-8">
            <div className="row between gap-8"><span className="row gap-8"><span className={`badge ${n.kind === "highlight" ? "badge-warn" : "badge-accent"}`}>{n.kind === "highlight" ? "Highlight" : "Note"}</span>{n.chapter_n && <span className="small muted">Ch. {n.chapter_n}</span>}<PageChip page={n.pdf_page} label={n.page_label} onOpen={setViewer} /></span>
              <button className="link-btn small" onClick={async () => { await api(`/notes/${n.id}`, { method: "DELETE" }); reload(true); }}>Delete</button></div>
            {n.quote && <p className="reading" style={{ fontSize: 16 }}>“{n.quote}”</p>}
            {n.text && <p>{n.kind === "highlight" ? <><strong>My note:</strong> {n.text}</> : n.text}</p>}
          </div>))}</div>}
      {viewer && <SourceViewer bookId={bookId!} page={viewer} onClose={() => setViewer(null)} />}
    </div>
  );
}
