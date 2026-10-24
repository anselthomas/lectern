import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, trackStudy } from "../api";
import { chName, chNo, ErrorBox, Loading, PageChip, SourceViewer, Spinner } from "../components";
import { VoiceInput } from "../voice";
import { useApi } from "../state";

/** Shared question runner for chapter quizzes and the final test. */
export function QuizRunner({ quiz, bookId, onSubmit, timed, header }: { quiz: any; bookId: string; onSubmit: (answers: Record<string, any>) => Promise<void>; timed?: number; header?: React.ReactNode }) {
  const [i, setI] = useState(0);
  const [answers, setAnswers] = useState<Record<string, any>>({});
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  const [viewer, setViewer] = useState<number | null>(null);
  const [left, setLeft] = useState(timed ? timed * 60 : 0);
  const [flags, setFlags] = useState<Set<string>>(new Set());
  useEffect(() => { if (!timed) return; const t = setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000); return () => clearInterval(t); }, [timed]);
  const q = quiz.questions[i];
  const last = i === quiz.questions.length - 1;
  const answer = answers[q.id];
  const check = async () => {
    setBusy(true); setErr(null);
    try { setResult(await api(`/quizzes/${quiz.id}/check`, { body: { question_id: q.id, answer } })); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const next = async () => {
    setResult(null);
    if (!last) { setI(i + 1); return; }
    setBusy(true); setErr(null);
    try { await onSubmit(answers); } catch (e) { setErr(e); setBusy(false); }
  };
  const instant = !timed; // the final test doesn't reveal answers until the end
  const answered = (id: string) => answers[id] !== undefined && answers[id] !== null && answers[id] !== "";
  const unanswered = quiz.questions.filter((x: any) => !answered(x.id)).length;
  const flagged = quiz.questions.filter((x: any) => flags.has(x.id)).length;
  // When time runs out the test is handed in as it stands.
  useEffect(() => {
    if (timed && left === 0 && !busy) { setBusy(true); onSubmit(answers).catch((e) => { setErr(e); setBusy(false); }); }
  }, [left]);
  return (
    <div className="stack gap-24">
      <div className="row between wrap gap-12">
        {header}
        <span className="mono muted">{i + 1} / {quiz.questions.length}{timed ? ` · ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` : ""}</span>
      </div>
      {timed ? (
        <nav className="qnav" aria-label="Questions">{quiz.questions.map((x: any, k: number) => (
          <button key={x.id} className={`${answered(x.id) ? "answered" : ""}${k === i ? " cur" : ""}${flags.has(x.id) ? " flagged" : ""}`} aria-current={k === i ? "step" : undefined}
            aria-label={`Question ${k + 1}${answered(x.id) ? ", answered" : ", not answered"}${flags.has(x.id) ? ", flagged" : ""}`} onClick={() => setI(k)}>{k + 1}</button>))}
        </nav>
      ) : <div className="steps">{quiz.questions.map((x: any, k: number) => <span key={x.id} className={k < i ? "done" : k === i ? "cur" : ""} />)}</div>}
      {timed && left > 0 && left <= 60 && <div className="alert alert-warn" role="status">Under a minute left. The test is handed in automatically at 0:00.</div>}
      {err && <ErrorBox error={err} />}
      <div className="card stack gap-16">
        <div className="row gap-8 wrap"><span className="badge badge-muted">{q.type === "mcq" ? "Multiple choice" : "Short answer"}</span>
          {q.section_title && <span className="small muted">Section {q.section_n} · {q.section_title}</span>}
          {q.chapter_title && <span className="small muted">{chName(q)}</span>}</div>
        <p style={{ fontSize: 19, fontWeight: 700, lineHeight: 1.45 }}>{q.question}</p>
        {q.type === "mcq" ? (
          <div className="stack gap-8" role="radiogroup" aria-label="Answer">
            {q.options.map((o: string, k: number) => {
              const cls = result ? (o === result.correct_answer ? " correct" : k === answer ? " wrong" : "") : "";
              return <button key={k} className={`option${cls}`} role="radio" aria-checked={answer === k} disabled={!!result} onClick={() => setAnswers({ ...answers, [q.id]: k })}><span className="key">{"ABCD"[k]}</span>{o}</button>;
            })}
          </div>
        ) : (
          <div className="field">
            <label htmlFor={`a-${q.id}`}>Your answer, in your own words</label>
            <textarea id={`a-${q.id}`} className="textarea" value={answer ?? ""} disabled={!!result} onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })} maxLength={2000} />
            <div className="row between wrap gap-8">
              <VoiceInput disabled={!!result} onText={(t) => setAnswers((a) => ({ ...a, [q.id]: a[q.id] ? `${String(a[q.id]).trim()} ${t}` : t }))} />
              <span className="small muted">Graded for the idea, not exact wording.</span>
            </div>
          </div>
        )}
        {result && (
          <div className={`alert ${result.correct ? "alert-ok" : "alert-error"} stack gap-8`} role="status">
            <span><strong>{result.correct ? "Correct." : "Not quite."}</strong> {result.feedback}</span>
            {!result.correct && q.type === "short" && <span><strong>A good answer:</strong> {result.correct_answer}</span>}
            {result.explanation && result.explanation !== result.feedback && <span className="small">{result.explanation}</span>}
            <PageChip page={result.page} label={result.page_label} onOpen={setViewer} />
          </div>
        )}
      </div>
      {timed && last && (unanswered > 0 || flagged > 0) && (
        <div className="alert alert-warn" role="status">{[unanswered && `${unanswered} unanswered`, flagged && `${flagged} flagged`].filter(Boolean).join(" · ")}. Use the numbers above to go back before you see your results.</div>)}
      <div className="row between wrap gap-12">
        {timed ? <button className="btn btn-ghost" onClick={() => { const f = new Set(flags); f.has(q.id) ? f.delete(q.id) : f.add(q.id); setFlags(f); }}>{flags.has(q.id) ? "★ Flagged" : "☆ Flag for review"}</button>
          : <button className="btn btn-ghost" disabled={!!result || busy} onClick={() => { setAnswers({ ...answers, [q.id]: null }); next(); }}>Skip</button>}
        <div className="row gap-8">
          {timed && i > 0 && <button className="btn btn-secondary" onClick={() => setI(i - 1)}>Back</button>}
          {instant && !result ? <button className="btn btn-strong" disabled={busy || answer === undefined || answer === ""} onClick={check}>{busy ? <Spinner /> : "Check answer"}</button>
            : <button className="btn btn-strong" disabled={busy} onClick={next}>{busy ? <><Spinner />Grading…</> : last ? "See results" : "Continue"}</button>}
        </div>
      </div>
      {viewer && <SourceViewer bookId={bookId} page={viewer} onClose={() => setViewer(null)} />}
    </div>
  );
}

export default function Quiz() {
  const { chapterId } = useParams();
  const { data: quiz, error } = useApi<any>(`/chapters/${chapterId}/quiz`);
  const [done, setDone] = useState<any>(null);
  useEffect(() => (quiz?.book?.id ? trackStudy(quiz.book.id) : undefined), [quiz?.book?.id]);
  if (error) return <div className="page-narrow stack gap-16"><ErrorBox error={error} /><Link to="/library">Back to library</Link></div>;
  if (!quiz) return <Loading label="Loading the quiz…" />;
  const ch = quiz.chapter;
  if (done) return (
    <div className="page-narrow stack gap-24">
      <div className="card stack gap-16" style={{ alignItems: "center", textAlign: "center" }}>
        <span style={{ fontSize: 48, fontWeight: 800 }}>{done.correct}/{done.total}</span>
        <h2>{done.mastered ? `Chapter ${chNo(ch)} mastered` : "Good effort — review and try again"}</h2>
        <p className="muted">{done.new_cards ? `You missed ${done.total - done.correct} question${done.total - done.correct === 1 ? "" : "s"}. ${done.new_cards === 1 ? "It's" : "They're"} now flashcard${done.new_cards === 1 ? "" : "s"}, scheduled for review.` : done.correct === done.total ? "A perfect score." : "Your misses are already in your review deck."}</p>
      </div>
      <div className="card stack gap-12"><span className="label">By section</span>
        {done.by_section.map((g: any) => (
          <div key={g.section_n} className="row between gap-12" style={{ padding: "8px 0", borderBottom: "1px solid var(--bg-3)" }}>
            <span>{chNo(ch)}.{g.section_n} {g.title}</span>
            <span className={`badge ${g.correct === g.total ? "badge-ok" : g.correct / g.total >= 0.5 ? "badge-warn" : "badge-bad"}`}>{g.correct} / {g.total}</span>
          </div>))}
      </div>
      <div className="row gap-12 wrap">
        {done.new_cards > 0 && <Link className="btn btn-secondary" to={`/review?book=${quiz.book.id}`}>Review the {done.total - done.correct} misses now</Link>}
        {done.next_chapter ? <Link className="btn btn-strong" to={`/books/${quiz.book.id}?chapter=${done.next_chapter.id}`}>Start chapter {done.next_chapter.n}</Link>
          : <Link className="btn btn-strong" to={`/books/${quiz.book.id}/final`}>Go to the final test</Link>}
        <Link className="btn btn-ghost" to={`/chapters/${ch.id}/quiz`} onClick={() => window.location.reload()}>Retake quiz</Link>
      </div>
    </div>
  );
  return (
    <div className="page-narrow">
      <QuizRunner quiz={quiz} bookId={quiz.book.id}
        header={<span className="small muted"><Link to={`/books/${quiz.book.id}?chapter=${ch.id}`}>{chName(ch)} · quiz</Link></span>}
        onSubmit={async (answers) => setDone(await api(`/quizzes/${quiz.id}/submit`, { body: { answers } }))} />
    </div>
  );
}
