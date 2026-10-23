import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { ErrorBox, Loading, Spinner } from "../components";
import { useApi } from "../state";

const levels = [
  { id: "new", title: "It's new to me", sub: "Start from the basics" },
  { id: "some", title: "I've seen some of it", sub: "Refresh, then go deeper" },
  { id: "confident", title: "I know it fairly well", sub: "Move quickly, focus on gaps" },
];

export default function PreQuestion() {
  const { chapterId } = useParams();
  const nav = useNavigate();
  const { data: ch, error } = useApi<any>(`/chapters/${chapterId}`);
  const [rating, setRating] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const [plan, setPlan] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  if (error) return <div className="page-narrow"><ErrorBox error={error} /></div>;
  if (!ch) return <Loading />;
  if (ch.status !== "ready") return <div className="page-narrow stack gap-16"><h2>Chapter {ch.n} is still being prepared</h2><Link to={`/books/${ch.book.id}?chapter=${ch.id}`}>Back to the chapter map</Link></div>;
  const first = ch.resume ?? ch.sections[0];
  const go = async () => {
    setBusy(true); setErr(null);
    try {
      const p = await api(`/chapters/${chapterId}/prequestion`, { body: { rating, answer } });
      setPlan(p);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <div className="page-narrow stack gap-24">
      <div className="stack gap-8">
        <span className="small muted"><Link to={`/books/${ch.book.id}?chapter=${ch.id}`}>Chapter {ch.n} · {ch.title}</Link> · Step 2 of 8 · Pre-question</span>
        <h1>Before you start</h1>
        <p className="reading">What do you already know about <strong>{ch.title.replace(/^Chapter \d+\s*/i, "")}</strong>? There's no wrong answer. This sets your starting point so we don't over-explain or skip too fast.</p>
      </div>
      {err && <ErrorBox error={err} />}
      <div className="stack gap-8" role="radiogroup" aria-label="What you know">
        {levels.map((l) => (
          <button key={l.id} className="option" role="radio" aria-checked={rating === l.id} onClick={() => setRating(l.id)} disabled={!!plan}>
            <span className="stack gap-4"><span>{l.title}</span><span className="small muted" style={{ fontWeight: 500 }}>{l.sub}</span></span>
          </button>))}
      </div>
      <div className="field">
        <label htmlFor="pre">In a sentence or two, what do you think it means? <span className="muted">(optional)</span></label>
        <textarea id="pre" className="textarea" value={answer} onChange={(e) => setAnswer(e.target.value)} disabled={!!plan} maxLength={2000} />
      </div>
      {plan && (
        <div className="card stack gap-8" role="status" style={{ borderColor: "var(--accent-soft-2)", background: "var(--accent-soft)" }}>
          <span className="eyebrow">Your plan</span>
          <p className="reading" style={{ fontSize: 17 }}>{plan.plan}</p>
          <span className="small muted">Suggested level: <strong>{plan.level}</strong>{plan.focus?.length ? ` · Focus: ${plan.focus.join(", ")}` : ""}</span>
        </div>
      )}
      <div className="row between wrap gap-12">
        <Link to={`/sections/${first.id}`} className="btn btn-ghost" onClick={async (e) => { if (!plan) { e.preventDefault(); setBusy(true); await api(`/chapters/${chapterId}/prequestion`, { body: { rating: "some", answer: "" } }).catch(() => undefined); nav(`/sections/${first.id}`); } }}>Skip</Link>
        {plan ? <Link className="btn btn-strong" to={`/sections/${first.id}?level=${plan.level}`}>Start section {ch.n}.{first.n} →</Link>
          : <button className="btn btn-strong" disabled={!rating || busy} onClick={go}>{busy ? <Spinner /> : "Get my plan"}</button>}
      </div>
    </div>
  );
}
