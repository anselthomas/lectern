import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, trackStudy } from "../api";
import { ErrorBox, Loading, PageChip, SourceViewer, Spinner } from "../components";
import { VoiceInput } from "../voice";
import { useApi } from "../state";

export default function Explain() {
  const { chapterId } = useParams();
  const { data: ch, error } = useApi<any>(`/chapters/${chapterId}`);
  const [text, setText] = useState("");
  const [fb, setFb] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  const [viewer, setViewer] = useState<number | null>(null);
  useEffect(() => { if (ch?.progress?.explain && !fb) { setText(ch.progress.explain.text); setFb(ch.progress.explain); } }, [ch]);
  useEffect(() => (ch?.book?.id ? trackStudy(ch.book.id) : undefined), [ch?.book?.id]);
  if (error) return <div className="page-narrow"><ErrorBox error={error} /></div>;
  if (!ch) return <Loading />;
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  const submit = async () => {
    setBusy(true); setErr(null);
    try { setFb(await api(`/chapters/${chapterId}/explain`, { body: { text } })); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const verdictCls = fb?.verdict === "Good explanation" ? "badge-ok" : fb?.verdict === "Getting there" ? "badge-warn" : "badge-bad";
  return (
    <div className="page-narrow stack gap-24">
      <span className="small muted"><Link to={`/books/${ch.book.id}?chapter=${ch.id}`}>Chapter {ch.n} · {ch.title}</Link> · Step 4 of 8 · Explain it back</span>
      <div className="stack gap-12">
        <h1>Explain it back</h1>
        <p className="reading">{ch.map?.explain?.prompt ?? "Explain the main idea of this chapter as if to a friend who missed class."}</p>
        <span className="muted">Aim for 2–4 sentences. Use an example if you can.</span>
      </div>
      {err && <ErrorBox error={err} />}
      <div className="field">
        <label htmlFor="exp">Your explanation</label>
        <textarea id="exp" className="textarea" style={{ minHeight: 160 }} value={text} onChange={(e) => { setText(e.target.value); }} maxLength={3000} />
        <div className="row between wrap gap-8">
          <VoiceInput disabled={!!fb} onText={(t) => setText((prev) => (prev.trim() ? `${prev.trim()} ${t}` : t))} />
          <span className="small muted">{words} words</span>
        </div>
      </div>
      {!fb && <button className="btn btn-strong" style={{ alignSelf: "flex-start" }} disabled={busy || words < 5} onClick={submit}>{busy ? <><Spinner />Reading your answer…</> : "Get feedback"}</button>}
      {fb && (
        <div className="card stack gap-16" role="status">
          <div className="row gap-12 wrap"><span className={`badge ${verdictCls}`}>{fb.verdict}</span><strong>{fb.met} of {fb.total} key points</strong></div>
          <ul className="stack gap-12" style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {fb.points?.map((p: any, i: number) => (
              <li key={i} className="row gap-12" style={{ alignItems: "flex-start" }}>
                <span aria-hidden="true" style={{ color: p.met ? "var(--ok)" : "var(--bad)", fontWeight: 800 }}>{p.met ? "✓" : "✕"}</span>
                <span className="stack gap-4"><strong>{p.met ? p.point : `Missing: ${p.point}`}</strong><span className="muted">{p.feedback}</span></span>
              </li>))}
          </ul>
          {fb.page && <span><PageChip page={fb.page} label={fb.page_label} onOpen={setViewer} /></span>}
          <div className="soft stack gap-8"><span className="label">A stronger version</span><p className="reading" style={{ fontSize: 17 }}>{fb.stronger_version}</p></div>
          <div className="row gap-12 wrap">
            <button className="btn btn-secondary" onClick={() => setFb(null)}>Try again</button>
            <Link className="btn btn-strong" to={`/chapters/${ch.id}/quiz`}>Continue to chapter quiz</Link>
          </div>
        </div>
      )}
      {viewer && <SourceViewer bookId={ch.book.id} page={viewer} onClose={() => setViewer(null)} />}
    </div>
  );
}
