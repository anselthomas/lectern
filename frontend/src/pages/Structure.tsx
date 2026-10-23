import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, showLimit } from "../api";
import { ErrorBox, Loading, SourceViewer, Spinner } from "../components";
import { useApi } from "../state";

type Row = { key: string; title: string; pdf_start: number; pdf_end: number; kind: string; check_note?: string | null; sel?: boolean };

const kinds = [["chapter", "Chapter"], ["appendix", "Appendix"], ["front", "Front matter"], ["back", "Back matter"]];

function Step({ state, title, body }: { state: "done" | "cur" | "todo"; title: string; body?: string }) {
  return (
    <li className="row gap-12" style={{ alignItems: "flex-start" }}>
      <span style={{ marginTop: 2 }}>{state === "done" ? <span className="ring done" /> : state === "cur" ? <Spinner /> : <span className="ring" />}</span>
      <span className="stack gap-4"><strong style={{ color: state === "todo" ? "var(--muted-2)" : undefined }}>{title}</strong>{body && <span className="small muted">{body}</span>}</span>
    </li>
  );
}

export default function Structure() {
  const { bookId } = useParams();
  const nav = useNavigate();
  const { data: book, error, reload, setData } = useApi<any>(`/books/${bookId}`);
  const [rows, setRows] = useState<Row[]>([]);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  const [viewer, setViewer] = useState<number | null>(null);

  const working = book && ["uploading", "queued", "processing"].includes(book.status);
  useEffect(() => {
    if (!working && !(book?.confirmed && book.chapters?.some((c: any) => ["queued", "building"].includes(c.status)))) return;
    const t = setInterval(() => reload(true), 2500);
    return () => clearInterval(t);
  }, [working, book?.confirmed, book?.chapters, reload]);
  useEffect(() => {
    if (book?.chapters && !dirty) setRows(book.chapters.map((c: any) => ({ key: c.id, title: c.title, pdf_start: c.pdf_start, pdf_end: c.pdf_end, kind: c.kind, check_note: c.check_note })));
  }, [book?.chapters]);

  const issues = useMemo(() => {
    const out: string[] = [];
    const sorted = [...rows].sort((a, b) => a.pdf_start - b.pdf_start);
    sorted.forEach((r, i) => {
      if (!r.title.trim()) out.push(`Row ${i + 1} needs a title.`);
      if (r.pdf_end < r.pdf_start) out.push(`"${r.title}" ends before it starts.`);
      if (book && r.pdf_end > book.pages) out.push(`"${r.title}" goes past the last page (${book.pages}).`);
      if (i > 0 && r.pdf_start <= sorted[i - 1].pdf_end) out.push(`"${r.title}" overlaps "${sorted[i - 1].title}".`);
    });
    return out;
  }, [rows, book]);

  if (error) return <div className="page"><ErrorBox error={error} retry={() => reload()} /></div>;
  if (!book) return <Loading />;

  const edit = (i: number, patch: Partial<Row>) => { setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r))); setDirty(true); };
  const selected = rows.map((r, i) => (r.sel ? i : -1)).filter((i) => i >= 0);
  const merge = () => {
    if (selected.length < 2) return;
    const [a, b] = [selected[0], selected[selected.length - 1]];
    const merged: Row = { ...rows[a], pdf_end: rows[b].pdf_end, sel: false, key: `m${Date.now()}` };
    setRows([...rows.slice(0, a), merged, ...rows.slice(b + 1)]); setDirty(true);
  };
  const split = () => {
    if (selected.length !== 1) return;
    const i = selected[0], r = rows[i];
    if (r.pdf_end <= r.pdf_start) return;
    const mid = Math.floor((r.pdf_start + r.pdf_end) / 2);
    setRows([...rows.slice(0, i), { ...r, pdf_end: mid, sel: false }, { ...r, key: `s${Date.now()}`, title: `${r.title} (part 2)`, pdf_start: mid + 1, sel: false }, ...rows.slice(i + 1)]);
    setDirty(true);
  };
  const save = async () => {
    const updated = await api(`/books/${bookId}/chapters`, { method: "PUT", body: { chapters: rows.map(({ title, pdf_start, pdf_end, kind }) => ({ title, pdf_start, pdf_end, kind })) } });
    setDirty(false); setData(updated); return updated;
  };
  const confirm = async () => {
    setBusy(true); setErr(null);
    try { if (dirty) await save(); await api(`/books/${bookId}/confirm`, { method: "POST" }); nav(`/books/${bookId}`); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  };

  const redetect = async () => {
    const built = book.chapters?.some((c: any) => c.status === "ready");
    if (!window.confirm(built ? "Detect the chapters again? Lessons and progress already built for this book will be rebuilt from scratch." : "Detect the chapters again from the PDF?")) return;
    setBusy(true); setErr(null);
    try { setData(await api(`/books/${bookId}/redetect`, { method: "POST" })); setDirty(false); reload(true); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  };

  const chapterCount = rows.filter((r) => r.kind === "chapter").length;
  const appendices = rows.filter((r) => r.kind === "appendix").length;
  const first = book.chapters?.find((c: any) => c.kind === "chapter");
  const step = (cond: boolean, cur: boolean) => (cond ? "done" : cur ? "cur" : "todo") as any;
  const found = !["uploading", "queued", "processing"].includes(book.status);

  return (
    <div className="page stack gap-24">
      <nav className="small muted"><Link to="/library">Library</Link> / {book.filename}</nav>
      <div className="row wrap gap-24" style={{ alignItems: "flex-start" }}>
        <aside className="card stack gap-16" style={{ flex: "1 1 300px", maxWidth: 380 }}>
          <div className="stack gap-4"><h3>{book.title}</h3><span className="small muted">{book.pages ? `${book.pages} pages · ` : ""}{(book.bytes / 1048576).toFixed(0)} MB</span></div>
          <div className="stack gap-4"><strong>Preparing your book</strong><span className="small muted">You can review chapters while chapter 1 is being built.</span></div>
          <ol className="stack gap-16" style={{ listStyle: "none", margin: 0, padding: 0 }}>
            <Step state="done" title="Uploaded" body={book.kind ? (book.kind === "scanned" ? "Scanned PDF — running OCR" : "Text PDF, no OCR needed") : undefined} />
            <Step state={step(found, !found)} title={found ? "Found the structure" : "Reading the PDF"}
              body={found ? (book.structure_source ? `From the PDF's ${book.structure_source === "bookmarks" ? "bookmarks" : book.structure_source === "contents" ? "contents page" : book.structure_source} · ${chapterCount} chapters` : undefined) : book.status_detail ?? undefined} />
            <Step state={step(found && book.page_offset != null, false)} title="Matched page numbers" body={book.page_offset != null ? `Printed page 1 = PDF page ${book.page_offset + 1}` : found ? "Using PDF page numbers" : undefined} />
            <Step state={step(first?.status === "ready", ["queued", "building"].includes(first?.status))} title="Building chapter 1 lessons" body={first?.status === "building" ? "Sections, quick checks and key terms" : first?.status === "ready" ? "Ready to start" : book.confirmed ? undefined : "Starts when you confirm the chapters"} />
            <Step state="todo" title="Later chapters" body="Built when you reach them" />
            <Step state={step(book.embed_status === "done", book.embed_status === "running")} title="Tutor search index" body={book.embed_status === "running" ? `${book.embedded_chunks} passages indexed` : book.embed_status === "done" ? `${book.embedded_chunks} passages indexed` : undefined} />
          </ol>
        </aside>

        <section className="stack gap-16" style={{ flex: "999 1 520px", minWidth: 0 }}>
          {err && <ErrorBox error={err} />}
          {working && <div className="card"><Loading label={book.status_detail ?? "Reading the PDF…"} /></div>}
          {book.status === "needs_password" && <PasswordForm bookId={bookId!} onDone={(b) => setData({ ...book, ...b })} />}
          {book.status === "failed" && (
            <div className="card stack gap-12">
              <h2>{book.status_detail === "scanned_requires_pro" ? "This is a scanned PDF" : "We couldn't read this PDF"}</h2>
              <p className="muted">{book.status_detail === "scanned_requires_pro" ? "Scanned books need OCR, which is part of Pro. Upgrade, or upload a text-based PDF." : book.status_detail}</p>
              <div className="row gap-12 wrap">
                {book.status_detail === "scanned_requires_pro" && <button className="btn btn-primary" onClick={() => showLimit("Scanned PDFs need Pro.")}>Upgrade to Pro</button>}
                <button className="btn btn-secondary" onClick={async () => { await api(`/books/${bookId}`, { method: "DELETE" }); nav("/library"); }}>Remove and try another file</button>
              </div>
            </div>
          )}
          {book.status === "no_structure" && <ManualChapters book={book} onDone={(b) => { setDirty(false); setData(b); }} onView={setViewer} />}
          {["review", "ready"].includes(book.status) && rows.length > 0 && (
            <div className="card stack gap-16">
              <div className="row between wrap gap-12">
                <div className="stack gap-4"><h2>Check the chapters</h2><span className="muted">Rename, merge or fix page ranges. Lessons follow this outline.</span></div>
                <div className="row gap-8 wrap">
                  <button className="btn btn-sm btn-secondary" disabled={selected.length < 2} onClick={merge} title="Select two or more rows to merge">Merge</button>
                  <button className="btn btn-sm btn-secondary" disabled={selected.length !== 1} onClick={split} title="Select one row to split in half">Split</button>
                  <button className="btn btn-sm btn-ghost" disabled={busy} onClick={redetect}>Detect chapters again</button>
                </div>
              </div>
              {rows.some((r) => r.check_note) && <div className="alert alert-warn">{rows.filter((r) => r.check_note).length} item to check. {rows.find((r) => r.check_note)?.check_note}</div>}
              {issues.length > 0 && <div className="alert alert-error">{issues[0]}</div>}
              <div style={{ overflowX: "auto" }}>
                <table className="table">
                  <thead><tr><th style={{ width: 36 }}><span className="sr-only">Select</span></th><th style={{ width: 32 }}>#</th><th>Title</th><th style={{ width: 210 }}>Pages (PDF)</th><th style={{ width: 128 }}>Type</th><th style={{ width: 120 }}>Status</th></tr></thead>
                  <tbody>{rows.map((r, i) => {
                    const built = book.chapters?.find((c: any) => c.id === r.key);
                    return (
                      <tr key={r.key} style={r.kind !== "chapter" && r.kind !== "appendix" ? { opacity: 0.6 } : undefined}>
                        <td><input type="checkbox" aria-label={`Select ${r.title}`} checked={!!r.sel} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, sel: e.target.checked } : x)))} /></td>
                        <td className="mono">{i + 1}</td>
                        <td style={{ minWidth: 160 }}><input className="input" aria-label="Chapter title" value={r.title} onChange={(e) => edit(i, { title: e.target.value })} /></td>
                        <td><div className="row gap-4">
                          <input className="input mono" style={{ width: 64, padding: "0 8px" }} type="number" min={1} aria-label="Start page" value={r.pdf_start} onChange={(e) => edit(i, { pdf_start: +e.target.value })} />
                          <span>–</span>
                          <input className="input mono" style={{ width: 64, padding: "0 8px" }} type="number" min={1} aria-label="End page" value={r.pdf_end} onChange={(e) => edit(i, { pdf_end: +e.target.value })} />
                          <button className="chip" onClick={() => setViewer(r.pdf_start)} aria-label={`Preview page ${r.pdf_start}`}>view</button>
                        </div></td>
                        <td><select className="select" style={{ height: 40, width: 120, padding: "0 8px" }} aria-label="Type" value={r.kind} onChange={(e) => edit(i, { kind: e.target.value })}>{kinds.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></td>
                        <td>{r.check_note ? <span className="badge badge-warn" title={r.check_note ?? undefined}>Check</span> : built?.status === "ready" ? <span className="badge badge-ok">Ready</span> : ["queued", "building"].includes(built?.status) ? <span className="badge badge-accent"><Spinner />Building</span> : <span className="badge badge-muted">{r.kind === "chapter" || r.kind === "appendix" ? "Looks right" : "Skipped"}</span>}</td>
                      </tr>);
                  })}</tbody>
                </table>
              </div>
              <div className="row between wrap gap-12">
                <span className="small muted">{chapterCount} chapters · {appendices} appendices · {book.pages} pages</span>
                <div className="row gap-12 wrap">
                  {dirty && <button className="btn btn-secondary" disabled={busy || issues.length > 0} onClick={() => save().catch(setErr)}>Save changes</button>}
                  <button className="btn btn-primary" disabled={busy || issues.length > 0} onClick={confirm}>{busy ? <Spinner /> : book.confirmed ? "Save and open chapter map" : "Looks right — open chapter map"}</button>
                </div>
              </div>
            </div>
          )}
        </section>
      </div>
      {viewer && <SourceViewer bookId={bookId!} page={viewer} onClose={() => setViewer(null)} />}
    </div>
  );
}

function PasswordForm({ bookId, onDone }: { bookId: string; onDone: (b: any) => void }) {
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try { onDone(await api(`/books/${bookId}/password`, { body: { password: pw } })); } catch (e) { setErr(e); } finally { setBusy(false); setPw(""); }
  };
  return (
    <form className="card stack gap-16" onSubmit={submit}>
      <h2>This PDF is password-protected</h2>
      {err && <ErrorBox error={err} />}
      <div className="field"><label htmlFor="pdfpw">PDF password</label><input id="pdfpw" className="input" type="password" value={pw} onChange={(e) => setPw(e.target.value)} />
        <span className="small muted">Used once to unlock the file. We don't store it.</span></div>
      <button className="btn btn-primary" disabled={busy || !pw}>{busy ? <Spinner /> : "Unlock PDF"}</button>
    </form>
  );
}

function ManualChapters({ book, onDone, onView }: { book: any; onDone: (b: any) => void; onView: (p: number) => void }) {
  const [starts, setStarts] = useState<number[]>([1]);
  const [page, setPage] = useState(1);
  const [parts, setParts] = useState(10);
  const [err, setErr] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const sorted = [...new Set(starts)].sort((a, b) => a - b);
  const saveManual = async () => {
    setBusy(true); setErr(null);
    try {
      const chapters = sorted.map((s, i) => ({ title: `Chapter ${i + 1}`, pdf_start: s, pdf_end: (sorted[i + 1] ?? book.pages + 1) - 1, kind: "chapter" }));
      onDone(await api(`/books/${book.id}/chapters`, { method: "PUT", body: { chapters } }));
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const equal = async () => {
    setBusy(true); setErr(null);
    try { onDone(await api(`/books/${book.id}/split`, { body: { parts } })); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <div className="card stack gap-16">
      <h2>We couldn't find chapters in this PDF.</h2>
      <p className="muted">It has no bookmarks or contents page we could read. Mark where each chapter starts, or let us split it into equal parts.</p>
      {err && <ErrorBox error={err} />}
      <div className="row gap-8 wrap" style={{ alignItems: "flex-end" }}>
        <div className="field"><label htmlFor="startp">Chapter starts on PDF page</label><input id="startp" className="input mono" type="number" min={1} max={book.pages} value={page} onChange={(e) => setPage(+e.target.value)} style={{ width: 140 }} /></div>
        <button className="btn btn-secondary" onClick={() => onView(page)}>Preview page</button>
        <button className="btn btn-strong" onClick={() => page >= 1 && page <= book.pages && setStarts([...starts, page])}>Add chapter start</button>
      </div>
      <div className="stack gap-8"><span className="label">Your chapters</span>
        {sorted.map((s, i) => <div key={s} className="row between card-sm"><span><strong>Chapter {i + 1}</strong> <span className="mono muted">p. {s}–{(sorted[i + 1] ?? book.pages + 1) - 1}</span></span>
          {s !== 1 && <button className="link-btn small" onClick={() => setStarts(starts.filter((x) => x !== s))}>Remove</button>}</div>)}
      </div>
      <div className="row between wrap gap-12">
        <div className="row gap-8"><span className="small">Split into</span><input className="input mono" style={{ width: 80, height: 40 }} type="number" min={1} max={100} value={parts} onChange={(e) => setParts(+e.target.value)} aria-label="Number of parts" /><button className="btn btn-sm btn-secondary" disabled={busy} onClick={equal}>equal parts instead</button></div>
        <button className="btn btn-primary" disabled={busy} onClick={saveManual}>Save chapters</button>
      </div>
    </div>
  );
}
