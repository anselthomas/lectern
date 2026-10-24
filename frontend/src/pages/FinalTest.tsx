import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, showLimit } from "../api";
import { chName, chNo, ErrorBox, Loading, PageChip, SourceViewer, Spinner } from "../components";
import { useApi } from "../state";
import { QuizRunner } from "./Quiz";

export default function FinalTest() {
  const { bookId } = useParams();
  const { data: book } = useApi<any>(`/books/${bookId}`);
  const { data: status, error } = useApi<any>(`/books/${bookId}/final`);
  const [quiz, setQuiz] = useState<any>(null);
  const [answers, setAnswers] = useState<Record<string, any>>({});
  const [viewer, setViewer] = useState<number | null>(null);
  const [done, setDone] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  if (error) return <div className="page-narrow"><ErrorBox error={error} /></div>;
  if (!status || !book) return <Loading />;
  const start = async () => {
    if (status.requires_pro) { showLimit("Final tests need Pro."); return; }
    setBusy(true); setErr(null);
    try { setQuiz(await api(`/books/${bookId}/final/start`, { method: "POST" })); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  if (done) return (
    <div className="page-narrow stack gap-24">
      <div className="card stack gap-12" style={{ alignItems: "center", textAlign: "center" }}>
        <span style={{ fontSize: 48, fontWeight: 800 }}>{Math.round(done.score * 100)}%</span>
        <h2>{done.passed ? "Book complete" : "Not quite — you need 75% to pass"}</h2>
        <p className="muted">{done.passed ? `You finished ${book.title}.` : "Your misses are now flashcards. Review them and try again — attempts are unlimited."}</p>
      </div>
      <div className="card stack gap-12"><span className="label">Score by chapter</span>
        {done.by_chapter.map((g: any) => <div key={g.chapter_n} className="row between" style={{ padding: "8px 0", borderBottom: "1px solid var(--bg-3)" }}><span>{chName(g)}</span><span className="mono">{Math.round((g.correct / g.total) * 100)}%</span></div>)}
      </div>
      <div className="card stack gap-16"><span className="label">Your answers</span>
        {quiz.questions.map((q: any, k: number) => {
          const r = done.results.find((x: any) => x.id === q.id);
          const mine = answers[q.id];
          const given = q.type === "mcq" ? (typeof mine === "number" ? q.options[mine] : null) : mine;
          return (
            <div key={q.id} className="stack gap-8" style={{ paddingBottom: 14, borderBottom: "1px solid var(--bg-3)" }}>
              <div className="row gap-8 wrap"><span className={`badge ${r?.correct ? "badge-ok" : "badge-warn"}`}>{r?.correct ? "Correct" : given ? "Missed" : "Not answered"}</span><span className="small muted">Q{k + 1} · Ch. {chNo(q)}</span></div>
              <strong>{q.question}</strong>
              {given && <span className="small"><span className="muted">You said:</span> {given}</span>}
              {!r?.correct && r?.correct_answer && <span className="small"><span className="muted">Answer:</span> {r.correct_answer}</span>}
              {!r?.correct && (r?.explanation || r?.feedback) && <span className="small muted">{r.explanation || r.feedback}</span>}
              <PageChip page={r?.page} label={r?.page_label} onOpen={setViewer} />
            </div>);
        })}
      </div>
      <div className="row gap-12 wrap">
        {done.passed && <button className="btn btn-secondary" onClick={() => window.print()}>Download certificate</button>}
        <Link className="btn btn-strong" to="/library">Start another book</Link>
        {!done.passed && <Link className="btn btn-secondary" to={`/review?book=${bookId}`}>Review weak cards</Link>}
      </div>
      {viewer && <SourceViewer bookId={bookId!} page={viewer} onClose={() => setViewer(null)} />}
    </div>
  );
  if (quiz) return (
    <div className="page-narrow">
      <QuizRunner quiz={quiz} bookId={bookId!} timed={quiz.minutes} header={<span className="small muted">{book.title} · Final test</span>}
        onSubmit={async (a) => { setAnswers(a); setDone(await api(`/quizzes/${quiz.id}/submit`, { body: { answers: a } })); }} />
    </div>
  );
  return (
    <div className="page-narrow stack gap-24">
      <span className="small muted"><Link to={`/books/${bookId}`}>{book.title}</Link> · Final test</span>
      <div className="card stack gap-16">
        <span className="eyebrow">{status.chapters_done} of {status.chapters_total} chapters done</span>
        <h1>{status.eligible ? "Ready for the final test?" : "Finish every chapter to unlock the final test"}</h1>
        <p className="muted">A cumulative test across the whole book. Questions lean toward chapters where your quiz scores were lowest.</p>
        {status.note && <div className="alert alert-info">{status.note}</div>}
        <div className="row gap-24 wrap">
          <div className="stack gap-4"><span className="label">Questions</span><strong>Up to 40</strong></div>
          <div className="stack gap-4"><span className="label">Pass mark</span><strong>75%</strong></div>
          <div className="stack gap-4"><span className="label">Attempts</span><strong>Unlimited</strong></div>
          {status.best != null && <div className="stack gap-4"><span className="label">Best</span><strong>{Math.round(status.best * 100)}%</strong></div>}
        </div>
        {err && <ErrorBox error={err} />}
        <div className="row gap-12 wrap">
          <button className="btn btn-strong" disabled={!status.eligible || busy} onClick={start}>{busy ? <Spinner /> : `Start final test${status.requires_pro ? " · Pro" : ""}`}</button>
          <Link className="btn btn-secondary" to={`/review?book=${bookId}`}>Review weak cards first</Link>
        </div>
      </div>
    </div>
  );
}
