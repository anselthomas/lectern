import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, download, showLimit } from "../api";
import { signOut } from "../auth";
import { DailyTimePicker, ErrorBox, Loading, Modal, Spinner, Toast } from "../components";
import { useMe } from "../state";

function Meter({ label, used, limit, unit = "" }: { label: string; used: number; limit: number | null; unit?: string }) {
  const pct = limit ? Math.min(100, (used / limit) * 100) : 0;
  return (
    <div className="stack gap-8">
      <div className="row between"><strong>{label}</strong><span className="small muted">{used}{unit} {limit != null ? `of ${limit}${unit}` : "· unlimited"}</span></div>
      <div className={`bar${pct > 85 ? "" : " ok"}`}><span style={{ width: `${limit ? pct : 4}%` }} /></div>
    </div>
  );
}

export default function Settings() {
  const { me, setMe } = useMe();
  const nav = useNavigate();
  const [form, setForm] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [del, setDel] = useState(false);
  const timer = useRef<number>();
  useEffect(() => { if (me && !form) setForm({ name: me.name ?? "", level_default: me.level_default, daily_minutes: me.daily_minutes, target_recall: me.target_recall, reminders: me.reminders }); }, [me]);
  if (!me || !form) return <Loading />;
  const u = me.usage;
  const canExam = u.limits_exempt || u.plan.limits.exam;
  const save = async (patch: any) => {
    setErr(null); setBusy(true);
    const next = { ...form, ...patch };
    try { const m = await api("/me", { method: "PATCH", body: next }); setForm(next); setMe(m); setToast("Saved"); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <div className="page-narrow stack gap-24">
      <h1>Settings</h1>
      {err && <ErrorBox error={err} />}
      <section className="card stack gap-16">
        <h3>Profile</h3>
        <div className="field"><label htmlFor="nm">Name</label><input id="nm" className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
        <div className="field"><label htmlFor="em">Email</label><input id="em" className="input" value={me.email} disabled /></div>
        <button className="btn btn-sm btn-strong" style={{ alignSelf: "flex-start" }} disabled={busy} onClick={() => save({})}>{busy ? <Spinner /> : "Save changes"}</button>
      </section>
      <section className="card stack gap-16">
        <h3>Study preferences</h3>
        <div className="stack gap-8"><strong>Default explanation level</strong><span className="small muted">Change per section any time</span>
          <div className="seg" role="radiogroup" aria-label="Default level">{[["simple", "Simple"], ["standard", "Standard"], ["exam", "Exam"]].map(([v, l]) =>
            <button key={v} role="radio" aria-checked={form.level_default === v} onClick={() => (v === "exam" && !canExam ? showLimit("Exam-level explanations need Pro.") : save({ level_default: v }))}>{l}{v === "exam" && !canExam ? " · Pro" : ""}</button>)}</div></div>
        <div className="stack gap-8"><strong>Daily goal</strong><span className="small muted">From 20 minutes to 12 hours. Sets session length and review load</span>
          <DailyTimePicker value={form.daily_minutes} onChange={(m) => { setForm({ ...form, daily_minutes: m }); window.clearTimeout(timer.current); timer.current = window.setTimeout(() => save({ daily_minutes: m }), 700); }} /></div>
        <div className="stack gap-8"><strong>Target recall</strong><span className="small muted">Higher means more frequent reviews</span>
          <div className="seg" role="radiogroup" aria-label="Target recall">{[0.85, 0.9, 0.95].map((r) => <button key={r} role="radio" aria-checked={Math.abs(form.target_recall - r) < 0.001} onClick={() => save({ target_recall: r })}>{Math.round(r * 100)}%</button>)}</div></div>
        <label className="row gap-12" style={{ cursor: "pointer" }}><input type="checkbox" checked={form.reminders} onChange={(e) => save({ reminders: e.target.checked })} style={{ width: 20, height: 20 }} /><span><strong>Review reminders</strong><br /><span className="small muted">In-app reminders when cards are due</span></span></label>
      </section>
      <section className="card stack gap-16">
        <div className="row between wrap gap-12">
          <div className="stack gap-4"><h3>Current plan</h3><span className="muted">{u.plan.name}{u.plan.price_month ? ` · $${u.plan.price_month}/mo` : u.plan.id === "free" ? " · free" : ""}{u.limits_exempt ? " · internal test account (no limits)" : ""}</span></div>
          {u.plan.id === "free" && <button className="btn btn-primary" onClick={() => showLimit("Get unlimited books with Pro")}>Upgrade to Pro</button>}
        </div>
        <span className="label">Usage this month</span>
        <Meter label="Books" used={u.books.used} limit={u.books.limit} />
        <Meter label="Storage" used={u.storage_mb.used} limit={u.storage_mb.limit} unit=" MB" />
        <Meter label="Tutor messages" used={u.tutor_messages.used} limit={u.tutor_messages.limit} />
        {u.voice_clips && <Meter label="Voice answers" used={u.voice_clips.used} limit={u.voice_clips.limit} />}
        <span className="small muted">Invoices will appear here once payments are switched on.</span>
      </section>
      <section className="card stack gap-16">
        <h3>Your data</h3>
        <div className="row between wrap gap-12"><span className="stack gap-4"><strong>Export flashcards</strong><span className="small muted">CSV that imports into Anki</span></span><button className="btn btn-sm btn-secondary" onClick={() => download("/me/cards.csv", "lectern-flashcards.csv")}>Export</button></div>
        <div className="row between wrap gap-12"><span className="stack gap-4"><strong>Download all my data</strong><span className="small muted">Books, notes, cards and chat history (JSON)</span></span><button className="btn btn-sm btn-secondary" onClick={() => download("/me/export", "lectern-export.json")}>Download</button></div>
        <div className="row between wrap gap-12"><span className="stack gap-4"><strong>Delete account</strong><span className="small muted">Removes all books and progress permanently</span></span><button className="btn btn-sm btn-danger" onClick={() => setDel(true)}>Delete…</button></div>
      </section>
      {del && <DeleteAccount email={me.email} onClose={() => setDel(false)} onDeleted={() => { signOut(); setMe(null); nav("/"); }} />}
      {toast && <Toast text={toast} onDone={() => setToast(null)} />}
    </div>
  );
}

function DeleteAccount({ email, onClose, onDeleted }: { email: string; onClose: () => void; onDeleted: () => void }) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  return (
    <Modal onClose={onClose} label="Delete account">
      <div className="stack gap-16">
        <h2>Delete your account?</h2>
        <p className="muted">This permanently removes your books, lessons, notes, flashcards and progress. It can't be undone.</p>
        {err && <ErrorBox error={err} />}
        <div className="field"><label htmlFor="conf">Type your email to confirm</label><input id="conf" className="input" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={email} /></div>
        <div className="row gap-12"><button className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn btn-danger" disabled={busy || typed.trim().toLowerCase() !== email.toLowerCase()} onClick={async () => { setBusy(true); try { await api("/me", { method: "DELETE" }); onDeleted(); } catch (e) { setErr(e); setBusy(false); } }}>{busy ? <Spinner /> : "Delete permanently"}</button></div>
      </div>
    </Modal>
  );
}
