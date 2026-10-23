import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorBox, Loading, Spinner } from "../components";
import { useApi } from "../state";

const stateBadge: Record<string, [string, string]> = {
  mastered: ["Mastered", "badge-ok"], in_progress: ["In progress", "badge-accent"], not_started: ["Not started", "badge-muted"],
};

export default function BookMap() {
  const { bookId } = useParams();
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const { data: book, error, reload } = useApi<any>(`/books/${bookId}`);
  const { data: prog } = useApi<any>("/progress?days=30");
  const learnable = book?.chapters?.filter((c: any) => c.kind === "chapter" || c.kind === "appendix") ?? [];
  const selectedId = params.get("chapter") || book?.current_chapter?.id || learnable[0]?.id;
  const { data: ch, error: chErr, reload: reloadCh } = useApi<any>(selectedId ? `/chapters/${selectedId}` : null, [selectedId]);
  useEffect(() => {
    if (!ch || !["queued", "building", "pending"].includes(ch.status)) return;
    const t = setInterval(() => { reloadCh(true); reload(true); }, 4000);
    return () => clearInterval(t);
  }, [ch?.status, reloadCh, reload]);
  useEffect(() => { if (book && !book.confirmed) nav(`/books/${bookId}/structure`, { replace: true }); }, [book]);

  if (error) return <div className="page"><ErrorBox error={error} retry={() => reload()} /></div>;
  if (!book) return <Loading />;
  const other = book.chapters.filter((c: any) => c.kind === "front" || c.kind === "back");
  const startHref = ch && (ch.progress.prequestion ? (ch.resume ? `/sections/${ch.resume.id}` : `/chapters/${ch.id}/explain`) : `/chapters/${ch.id}/start`);

  return (
    <div className="page stack gap-24">
      <nav className="small muted"><Link to="/library">Library</Link> / {book.title}</nav>
      <div className="row between wrap gap-16">
        <div className="stack gap-4"><h1>{book.title}</h1><span className="muted">{book.chapters_total} chapters · {book.pages} pages</span></div>
        <div className="row gap-8 wrap">
          <Link className="btn btn-sm btn-secondary" to={`/books/${bookId}/notes`}>Notes & highlights</Link>
          <Link className="btn btn-sm btn-secondary" to={`/books/${bookId}/structure`}>Edit chapters</Link>
          <Link className="btn btn-sm btn-secondary" to={`/books/${bookId}/final`}>Final test</Link>
        </div>
      </div>
      <div className="row gap-16 wrap">
        <div className="card-sm grow stack gap-8" style={{ flexBasis: 220 }}><span className="label">Book progress</span><strong style={{ fontSize: 24 }}>{Math.round(book.progress)}%</strong><div className="bar ok"><span style={{ width: `${book.progress}%` }} /></div></div>
        <div className="card-sm grow stack gap-8" style={{ flexBasis: 160 }}><span className="label">Mastered</span><strong style={{ fontSize: 24 }}>{book.chapters_mastered} of {book.chapters_total}</strong></div>
        <div className="card-sm grow stack gap-8" style={{ flexBasis: 160 }}><span className="label">Day streak</span><strong style={{ fontSize: 24 }}>{prog?.streak ?? 0}</strong></div>
      </div>
      <div className="row wrap gap-24" style={{ alignItems: "flex-start" }}>
        <nav aria-label="Chapters" className="card stack gap-4" style={{ flex: "1 1 300px", maxWidth: 400, padding: 12, maxHeight: "70vh", overflowY: "auto" }}>
          {learnable.map((c: any) => {
            const [l, cls] = stateBadge[c.state];
            const cur = c.id === selectedId;
            return (
              <button key={c.id} onClick={() => setParams({ chapter: c.id })} aria-current={cur ? "true" : undefined}
                className="row gap-12" style={{ textAlign: "left", padding: "12px 10px", borderRadius: 10, border: 0, cursor: "pointer", background: cur ? "var(--accent-soft)" : "transparent" }}>
                <span className="mono muted" style={{ width: 22 }}>{c.n}</span>
                <span className="grow stack gap-4"><span style={{ fontWeight: cur ? 800 : 600, lineHeight: 1.35 }}>{c.title}</span>
                  <span className="row gap-8"><span className={`badge ${cls}`}>{l}</span>{c.status === "building" && <span className="badge badge-accent"><Spinner />Building</span>}</span></span>
              </button>);
          })}
          {other.length > 0 && <details style={{ padding: "8px 10px" }}><summary className="small muted" style={{ cursor: "pointer" }}>{other.length} front and back matter sections (not taught)</summary>
            <ul className="small muted" style={{ paddingLeft: 18 }}>{other.map((c: any) => <li key={c.id}>{c.title}</li>)}</ul></details>}
        </nav>
        <section className="stack gap-16" style={{ flex: "999 1 480px", minWidth: 0 }}>
          {chErr && <ErrorBox error={chErr} retry={() => reloadCh()} />}
          {!ch && !chErr && <div className="card"><Loading /></div>}
          {ch && ch.status !== "ready" && (
            <div className="card stack gap-12">
              <span className="eyebrow">Chapter {ch.n} map</span><h2>{ch.title}</h2>
              {ch.status === "failed" ? <>
                <div className="alert alert-error">We couldn't build this chapter. {ch.status_detail ? "" : ""}Try again — it usually works on a second attempt.</div>
                <button className="btn btn-primary" onClick={async () => { await api(`/chapters/${ch.id}/build`, { method: "POST" }); reloadCh(); }}>Build again</button>
              </> : <div className="row gap-12"><Spinner large /><div className="stack gap-4"><strong>Building lessons for this chapter</strong><span className="small muted">Sections, quick checks, key terms and the quiz. This takes a minute or two — we'll notify you when it's ready.</span></div></div>}
            </div>
          )}
          {ch && ch.status === "ready" && (
            <div className="card stack gap-24">
              <div className="row between wrap gap-16">
                <div className="stack gap-4"><span className="eyebrow">Chapter {ch.n} map</span><h2>{ch.title}</h2><span className="mono muted">pp. {ch.pages_label}</span></div>
                <Link className="btn btn-strong" to={startHref}>{ch.progress.mastered ? "Review this chapter" : ch.progress.prequestion ? (ch.resume ? `Resume section ${ch.n}.${ch.resume.n}` : "Continue") : "Start chapter"}</Link>
              </div>
              <div className="row gap-24 wrap">
                <div className="stack gap-4"><span className="label">Difficulty</span><strong>{ch.map?.difficulty}</strong></div>
                <div className="stack gap-4"><span className="label">Time</span><strong>~{ch.map?.minutes} min</strong></div>
                <div className="stack gap-4"><span className="label">Sections</span><strong>{ch.progress.sections_done} of {ch.sections.length} done</strong></div>
                {ch.progress.quiz_best != null && <div className="stack gap-4"><span className="label">Best quiz</span><strong>{Math.round(ch.progress.quiz_best * 100)}%</strong></div>}
              </div>
              <div className="stack gap-8"><span className="label">Key ideas</span>
                <ul className="stack gap-8 reading" style={{ margin: 0, paddingLeft: 22, fontSize: 17 }}>{ch.map?.key_ideas?.map((k: string) => <li key={k}>{k}</li>)}</ul></div>
              <div className="stack gap-4"><span className="label">Sections</span>
                {ch.sections.map((s: any) => (
                  <Link key={s.id} to={ch.progress.prequestion ? `/sections/${s.id}` : `/chapters/${ch.id}/start`} className="row gap-12" style={{ padding: "12px 4px", borderBottom: "1px solid var(--bg-3)", textDecoration: "none", color: "inherit" }}>
                    <span className={`ring${s.done ? " done" : ch.resume?.id === s.id ? " cur" : ""}`} />
                    <span className="grow stack gap-4"><strong>{ch.n}.{s.n} {s.title}</strong>{s.summary && <span className="small muted">{s.summary}</span>}</span>
                    <span className="mono muted">pp. {s.pages_label}</span>
                  </Link>))}
              </div>
              <div className="soft stack gap-8">
                <span className="label">After this chapter</span>
                <span><strong>Explain it back</strong>, then the <strong>chapter quiz · {ch.quiz?.count ?? 10} questions</strong>. Missed questions become flashcards.</span>
                {ch.progress.sections_done === ch.sections.length
                  ? <div className="row gap-8 wrap"><Link className="btn btn-sm btn-secondary" to={`/chapters/${ch.id}/explain`}>Explain it back</Link><Link className="btn btn-sm btn-primary" to={`/chapters/${ch.id}/quiz`}>Take the quiz</Link></div>
                  : <span className="small muted">Unlocks when all sections are done.</span>}
              </div>
              {ch.due_cards > 0 && <div className="row between card-sm" style={{ borderColor: "var(--warn-soft)", background: "var(--warn-soft)" }}>
                <span><strong>Needs attention</strong> · {ch.due_cards} card{ch.due_cards === 1 ? "" : "s"} due from this chapter</span><Link to={`/review?book=${bookId}`}>Review →</Link></div>}
              {ch.next_chapter && <span className="small muted">Next up: Chapter {ch.next_chapter.n}, {ch.next_chapter.title} {ch.next_chapter.status === "ready" ? "(ready)" : ["queued", "building"].includes(ch.next_chapter.status) ? "(being prepared now)" : ""}</span>}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
