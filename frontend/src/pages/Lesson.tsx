import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError, trackStudy } from "../api";
import { ErrorBox, Loading, PageChip, Rich, RichBlock, SourceViewer, Spinner, TopNav } from "../components";
import { useMe } from "../state";

const LEVELS = [["simple", "Simple"], ["standard", "Standard"], ["exam", "Exam"]];

function QuickCheck({ q, i, total, onOpen, compact, id }: { q: any; i: number; total: number; onOpen: (p: number) => void; compact?: boolean; id?: string }) {
  const [pick, setPick] = useState<number | null>(null);
  const [checked, setChecked] = useState(false);
  const right = pick === q.answer_index;
  const hid = id ?? `qc-${i}`;
  return (
    <section className={`card stack ${compact ? "gap-12" : "gap-16"}`} style={compact ? { padding: 14 } : undefined} aria-labelledby={hid}>
      <div className="row between"><h2 id={hid} className="eyebrow" style={{ fontSize: compact ? 11 : 13 }}>{compact ? "Tutor quiz" : "Quick check"}</h2>{!compact && <span className="small muted">{i + 1} of {total}</span>}</div>
      <p style={{ fontSize: compact ? 15 : 18, fontWeight: 700, lineHeight: 1.45 }}>{q.question}</p>
      <div className="stack gap-8" role="radiogroup" aria-label="Answer">
        {q.options.map((o: string, k: number) => {
          const cls = checked ? (k === q.answer_index ? " correct" : k === pick ? " wrong" : "") : "";
          return <button key={k} className={`option${cls}`} role="radio" aria-checked={pick === k} disabled={checked} onClick={() => setPick(k)}><span className="key">{"ABCD"[k]}</span>{o}</button>;
        })}
      </div>
      {!checked ? <button className="btn btn-sm btn-strong" style={{ alignSelf: "flex-start" }} disabled={pick === null} onClick={() => setChecked(true)}>Check</button>
        : <div className={`alert ${right ? "alert-ok" : "alert-error"} stack gap-8`} role="status"><span><strong>{right ? "Correct." : "Not quite."}</strong> {q.explanation}</span><PageChip page={q.page} label={q.page_label} onOpen={onOpen} /></div>}
    </section>
  );
}

function Tutor({ bookId, chapterId, sectionId, level, onOpen, onClose }: { bookId: string; chapterId: string; sectionId: string; level: string; onOpen: (p: number, quote?: string) => void; onClose: () => void }) {
  const [log, setLog] = useState<any[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { api(`/tutor/${bookId}/history`).then(setLog).catch(() => undefined); }, [bookId]);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [log, busy]);
  const ask = async (message: string) => {
    if (!message.trim() || busy) return;
    setErr(null); setBusy(true); setText("");
    setLog((l) => [...l, { role: "user", text: message }]);
    try {
      const r = await api("/tutor", { body: { book_id: bookId, chapter_id: chapterId, section_id: sectionId, message, level } });
      setLog((l) => [...l, { role: "assistant", text: r.answer, citations: r.citations, follow_ups: r.follow_ups, in_book: r.in_book, quiz: r.quiz }]);
    } catch (e) {
      setLog((l) => l.slice(0, -1)); setText(message);
      if (!(e instanceof ApiError && e.status === 402)) setErr(e);
    } finally { setBusy(false); }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); ask(text); };
  const last = [...log].reverse().find((m) => m.role === "assistant");
  const suggestions = last?.follow_ups?.length ? last.follow_ups : ["Give me a real-life example", "Quiz me on this section", "Explain this more simply"];
  return (
    <aside className="tutor" aria-label="Tutor">
      <div className="row between" style={{ padding: "18px 20px", borderBottom: "1px solid var(--line)" }}>
        <div className="stack gap-4"><strong style={{ fontSize: 16 }}>Tutor</strong><span className="tiny muted">Answers only from this book</span></div>
        <button className="icon-btn" aria-label="Close tutor" onClick={onClose}>✕</button>
      </div>
      <div className="tutor-log" aria-live="polite">
        {log.length === 0 && <p className="small muted">Ask about anything in this book. Answers cite the pages they come from.</p>}
        {log.map((m, i) => m.role === "user" ? <div key={i} className="bubble-me">{m.text}</div> : (
          <div key={i} className="stack gap-8" style={{ maxWidth: "94%" }}>
            <div className="bubble-ai"><RichBlock text={m.text} /></div>
            {m.quiz && <QuickCheck q={m.quiz} i={0} total={1} compact id={`tq-${i}`} onOpen={(p) => onOpen(p)} />}
            {m.citations?.length > 0 && <div className="row gap-4 wrap">{m.citations.map((c: any) => <PageChip key={c.pdf_page} page={c.pdf_page} label={c.label} onOpen={(p) => onOpen(p, m.text.slice(0, 140))} />)}</div>}
          </div>))}
        {busy && <div className="row gap-8 small muted"><Spinner />Looking through the book…</div>}
        {err && <ErrorBox error={err} />}
        <div ref={end} />
      </div>
      <div className="stack gap-8" style={{ padding: 16, borderTop: "1px solid var(--line)" }}>
        <span className="tiny label">Try asking</span>
        <div className="row gap-4 wrap">{suggestions.slice(0, 3).map((s: string) => <button key={s} className="btn btn-sm btn-secondary" style={{ height: "auto", minHeight: 36, padding: "6px 12px", whiteSpace: "normal", textAlign: "left" }} disabled={busy} onClick={() => ask(s)}>{s}</button>)}</div>
        <form className="row gap-8" onSubmit={submit}>
          <input className="input" placeholder="Ask the tutor" aria-label="Ask the tutor" value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} />
          <button className="btn btn-primary" disabled={busy || !text.trim()} aria-label="Send">↑</button>
        </form>
      </div>
    </aside>
  );
}

export default function Lesson() {
  const { sectionId } = useParams();
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const { me } = useMe();
  const level = params.get("level") || me?.level_default || "standard";
  const [sec, setSec] = useState<any>(null);
  const [err, setErr] = useState<any>(null);
  const [viewer, setViewer] = useState<{ page: number; quote?: string } | null>(null);
  const [tutorOpen, setTutorOpen] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true, timer: number | undefined;
    const load = async () => {
      try {
        const s = await api(`/sections/${sectionId}?level=${level}`);
        if (!alive) return;
        setSec(s); setErr(null);
        if (s.status === "building") timer = window.setTimeout(load, 3500);
      } catch (e) {
        if (!alive) return;
        if (e instanceof ApiError && e.status === 402) { setParams({ level: "standard" }); return; }
        setErr(e);
      }
    };
    load();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [sectionId, level]);
  useEffect(() => (sec?.book?.id ? trackStudy(sec.book.id) : undefined), [sec?.book?.id]);

  if (err) return <><TopNav /><div className="page"><ErrorBox error={err} /></div></>;
  if (!sec) return <><TopNav /><Loading label="Opening the lesson…" /></>;
  const ch = sec.chapter;
  const doneIdx = ch.sections.findIndex((s: any) => s.id === sec.id);
  const finish = async () => {
    setBusy(true);
    try {
      await api(`/sections/${sec.id}/complete`, { method: "POST" });
      nav(sec.next ? `/sections/${sec.next.id}?level=${level}` : `/chapters/${ch.id}/explain`);
    } finally { setBusy(false); }
  };
  const open = (page: number, quote?: string) => setViewer({ page, quote });
  const lesson = sec.lesson;
  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <div className="lesson-top">
        <Link to={`/books/${sec.book.id}?chapter=${ch.id}`} className="row gap-8" style={{ color: "var(--muted)", textDecoration: "none", fontWeight: 600, fontSize: 14, padding: "12px 0" }}>← Ch. {ch.n} · {ch.title}</Link>
        <div className="steps" role="img" aria-label={`Section ${sec.n} of ${ch.sections.length}`} style={{ flex: "1 1 200px", maxWidth: 360 }}>
          {ch.sections.map((s: any, i: number) => <span key={s.id} className={s.done ? "done" : i === doneIdx ? "cur" : ""} />)}
        </div>
        <span className="grow" />
        <div className="seg" role="radiogroup" aria-label="Explanation level">
          {LEVELS.map(([v, l]) => <button key={v} role="radio" aria-checked={level === v} onClick={() => setParams({ level: v })}>{l}{v === "exam" && !(me?.usage?.limits_exempt || me?.usage?.plan?.limits?.exam) ? " · Pro" : ""}</button>)}
        </div>
        {!tutorOpen && <button className="btn btn-sm btn-secondary" onClick={() => setTutorOpen(true)}>Ask the tutor</button>}
      </div>
      <div className="lesson-shell">
        <nav className="lesson-rail" aria-label="Sections">
          <span className="label" style={{ padding: "0 10px 10px" }}>Sections</span>
          {ch.sections.map((s: any) => (
            <Link key={s.id} to={`/sections/${s.id}?level=${level}`} aria-current={s.id === sec.id ? "step" : undefined}>
              <span className={`ring${s.done ? " done" : s.id === sec.id ? " cur" : ""}`} />{ch.n}.{s.n} {s.title}
            </Link>))}
          <Link to={`/chapters/${ch.id}/explain`} style={{ marginTop: 8, borderTop: "1px solid var(--bg-3)" }}>✎ Explain it back</Link>
          <Link to={`/chapters/${ch.id}/quiz`}>☑ Chapter quiz</Link>
        </nav>
        <main className="lesson-main">
          <article>
            <div className="stack gap-8">
              <span className="mono muted">Section {ch.n}.{sec.n} · pp. {sec.pages_label}{lesson?.minutes ? ` · ~${lesson.minutes} min` : ""}</span>
              <h1>{sec.title}</h1>
            </div>
            {sec.status === "building" && <div className="card row gap-12"><Spinner large /><div className="stack gap-4"><strong>Writing this section at the {level} level</strong><span className="small muted">Usually 20–40 seconds.</span></div></div>}
            {lesson && <>
              {lesson.blocks.map((b: any, i: number) => {
                if (b.type === "heading") return <h2 key={i} style={{ fontSize: 22 }}>{b.text}</h2>;
                if (b.type === "key_term") return (
                  <div key={i} className="card stack gap-8" style={{ padding: 20 }}>
                    <span className="eyebrow">Key term</span><strong style={{ fontSize: 17 }}>{b.term}</strong>
                    <span className="reading" style={{ fontSize: 16, color: "var(--ink-3)" }}><Rich text={b.text} /></span>
                    <span><PageChip page={b.page} label={b.page_label} onOpen={(p) => open(p, b.text)} /></span>
                  </div>);
                if (b.type === "example" || b.type === "formula") return (
                  <div key={i} className="soft stack gap-8" style={{ borderLeft: "4px solid var(--accent)", borderRadius: 10, padding: 18 }}>
                    <span className="eyebrow">{b.type === "formula" ? "Formula" : "Example"}</span>
                    <p className="reading" style={{ fontSize: 17, fontFamily: b.type === "formula" ? "var(--mono)" : undefined }}><Rich text={b.text} /></p>
                    <span><PageChip page={b.page} label={b.page_label} onOpen={(p) => open(p, b.text)} /></span>
                  </div>);
                return <div key={i} className="stack gap-8"><p className="reading"><Rich text={b.text} /></p>{b.page && <span><PageChip page={b.page} label={b.page_label} onOpen={(p) => open(p, b.text)} /></span>}</div>;
              })}
              {lesson.quick_checks.map((q: any, i: number) => <QuickCheck key={`${sec.id}-${level}-${i}`} q={q} i={i} total={lesson.quick_checks.length} onOpen={(p) => open(p)} />)}
            </>}
            <div className="row between wrap gap-12" style={{ paddingTop: 8 }}>
              {sec.prev ? <Link to={`/sections/${sec.prev.id}?level=${level}`} style={{ fontWeight: 700, padding: "12px 0" }}>← {ch.n}.{sec.prev.n} {sec.prev.title}</Link> : <span />}
              <button className="btn btn-strong" disabled={busy || !lesson} onClick={finish}>{busy ? <Spinner /> : sec.next ? `Next: ${ch.n}.${sec.next.n} →` : "Next: explain it back →"}</button>
            </div>
          </article>
        </main>
        {tutorOpen && <Tutor bookId={sec.book.id} chapterId={ch.id} sectionId={sec.id} level={level} onOpen={open} onClose={() => setTutorOpen(false)} />}
      </div>
      {viewer && <SourceViewer bookId={sec.book.id} page={viewer.page} quote={viewer.quote} onClose={() => setViewer(null)} />}
    </div>
  );
}
