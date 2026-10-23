import { DragEvent, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError, showLimit, uploadToS3 } from "../api";
import { Cover, ErrorBox, Loading, Spinner } from "../components";
import { useApi, useMe } from "../state";

export function UploadBox({ onDone }: { onDone: (book: any) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [err, setErr] = useState<any>(null);
  const start = async (f: File) => {
    setErr(null);
    if (!f.name.toLowerCase().endsWith(".pdf") && f.type !== "application/pdf") { setErr(new Error("That isn't a PDF. Choose a .pdf file.")); return; }
    setFile(f); setProgress(0);
    try {
      const { book, upload_url } = await api("/books", { body: { filename: f.name, size: f.size } });
      await uploadToS3(upload_url, f, setProgress);
      const done = await api(`/books/${book.id}/uploaded`, { method: "POST" });
      onDone(done);
    } catch (e) {
      setProgress(null); setFile(null);
      if (!(e instanceof ApiError && e.status === 402)) setErr(e);
    }
  };
  const drop = (e: DragEvent) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files?.[0]; if (f) start(f); };
  return (
    <div className="stack gap-12">
      {err && <ErrorBox error={err} />}
      <div className={`dropzone${over ? " over" : ""}`} role="button" tabIndex={0} aria-label="Upload a PDF"
        onClick={() => progress === null && input.current?.click()} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={drop}>
        <input ref={input} type="file" accept="application/pdf,.pdf" hidden data-testid="pdf-input" onChange={(e) => e.target.files?.[0] && start(e.target.files[0])} />
        {progress === null ? (
          <div className="stack gap-8" style={{ alignItems: "center" }}>
            <strong style={{ fontSize: 17 }}>Drop a PDF here or <span style={{ color: "var(--accent)" }}>browse your files</span></strong>
            <span className="small muted">Textbooks, manuals and long reports. We never send the whole book to a model at once.</span>
          </div>
        ) : (
          <div className="stack gap-12" style={{ alignItems: "stretch", maxWidth: 420, margin: "0 auto" }}>
            <div className="row between gap-12"><strong className="grow" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{file?.name}</strong><span className="mono">{file ? `${(file.size / 1048576).toFixed(1)} MB` : ""}</span></div>
            <div className="bar"><span style={{ width: `${Math.round(progress * 100)}%` }} /></div>
            <span className="small muted">{progress < 1 ? `Uploading… ${Math.round(progress * 100)}%` : "Upload complete. Starting to read the PDF…"}</span>
          </div>
        )}
      </div>
    </div>
  );
}

const statusLabel: Record<string, [string, string]> = {
  uploading: ["Uploading", "badge-muted"], queued: ["Queued", "badge-muted"], processing: ["Reading PDF", "badge-accent"],
  needs_password: ["Needs password", "badge-warn"], no_structure: ["Needs chapters", "badge-warn"], review: ["Check chapters", "badge-warn"],
  ready: ["Ready", "badge-ok"], failed: ["Couldn't read", "badge-bad"],
};

export default function Library() {
  const { me } = useMe();
  const nav = useNavigate();
  const { data: books, error, loading, reload } = useApi<any[]>("/books");
  const { data: due } = useApi<any>("/review/due");
  const [adding, setAdding] = useState(false);
  if (loading && !books) return <Loading label="Loading your library…" />;
  const usage = me?.usage;
  const atLimit = usage?.books?.limit != null && (books?.length ?? 0) >= usage.books.limit;
  return (
    <div className="page stack gap-24">
      <div className="row between wrap gap-16">
        <div className="stack gap-4"><h1>Your library</h1>
          <span className="muted">{usage?.plan?.name} plan · {books?.length ?? 0}{usage?.books?.limit != null ? ` of ${usage.books.limit}` : ""} book{(books?.length ?? 0) === 1 ? "" : "s"}{usage?.limits_exempt ? " · internal test account, no limits" : ""}</span></div>
        <button className="btn btn-primary" onClick={() => (atLimit ? showLimit("You've used your free book") : setAdding(!adding))}>Upload PDF</button>
      </div>
      {error && <ErrorBox error={error} retry={() => reload()} />}
      {due?.cards?.length > 0 && (
        <div className="card-sm row between wrap gap-12" style={{ background: "var(--accent-soft)", borderColor: "var(--accent-soft-2)" }}>
          <div className="stack gap-4"><strong>{due.cards.length} flashcard{due.cards.length === 1 ? "" : "s"} due</strong><span className="small muted">A few minutes now keeps them from slipping.</span></div>
          <Link className="btn btn-sm btn-strong" to="/review">Start review</Link>
        </div>
      )}
      {adding && <div className="card stack gap-12"><h3>Add a book</h3><UploadBox onDone={(b) => nav(`/books/${b.id}/structure`)} /></div>}
      {books && books.length === 0 && !adding && (
        <div className="card empty">
          <h2>Your shelf is empty</h2>
          <p className="muted" style={{ maxWidth: 460 }}>Upload a textbook or manual. We'll find the chapters and build your first lesson in a few minutes.</p>
          <div style={{ width: "100%", maxWidth: 560 }}><UploadBox onDone={(b) => nav(`/books/${b.id}/structure`)} /></div>
        </div>
      )}
      <div className="book-grid">
        {books?.map((b) => {
          const [label, cls] = statusLabel[b.status] ?? [b.status, "badge-muted"];
          const href = b.status === "ready" ? `/books/${b.id}` : `/books/${b.id}/structure`;
          return (
            <Link key={b.id} to={href} className="card row gap-16" style={{ textDecoration: "none", color: "inherit", alignItems: "flex-start" }}>
              <Cover title={b.title} />
              <div className="stack gap-8 grow">
                <strong style={{ fontSize: 16, lineHeight: 1.35 }}>{b.title}</strong>
                <span className="small muted">{b.pages ? `${b.pages} pages · ` : ""}{b.chapters_total ? `${b.chapters_total} chapters` : b.filename}</span>
                {b.status === "ready" ? <>
                  <div className="bar ok"><span style={{ width: `${b.progress}%` }} /></div>
                  <span className="small">{b.current_chapter ? `Chapter ${b.current_chapter.n}: ${b.current_chapter.title}` : "All chapters mastered"}</span>
                </> : <span><span className={`badge ${cls}`}>{["processing", "queued"].includes(b.status) && <Spinner />}{label}</span></span>}
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
