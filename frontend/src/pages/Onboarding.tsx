import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { Brand, ErrorBox, Spinner } from "../components";
import { useMe } from "../state";
import { UploadBox } from "./Library";

const goals = [
  { id: "exam", level: "exam", title: "An exam or certification", body: "Exam-level detail, worked examples and the traps examiners test.", pro: true },
  { id: "course", level: "standard", title: "A course I'm taking", body: "Clear textbook-level explanations that keep pace with class." },
  { id: "work", level: "standard", title: "Work or a project", body: "Get to the useful parts quickly, with examples." },
  { id: "curious", level: "simple", title: "Curiosity", body: "Plain words and everyday examples. No jargon until it's needed." },
];
const paces = [{ m: 10, label: "10 min" }, { m: 20, label: "20 min" }, { m: 45, label: "45 min" }];

export default function Onboarding() {
  const { me, setMe } = useMe();
  const nav = useNavigate();
  const [step, setStep] = useState(0);
  const [goal, setGoal] = useState("course");
  const [minutes, setMinutes] = useState(20);
  const [reminders, setReminders] = useState(true);
  const [err, setErr] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const canExam = me?.usage?.limits_exempt || me?.usage?.plan?.limits?.exam;
  const save = async (onboarded: boolean) => {
    setBusy(true); setErr(null);
    const g = goals.find((x) => x.id === goal)!;
    try {
      const m = await api("/me", { method: "PATCH", body: { goal, level_default: g.level === "exam" && !canExam ? "standard" : g.level, daily_minutes: minutes, reminders, onboarded } });
      setMe(m);
      return m;
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const names = ["Your goal", "Your pace", "Your first book"];
  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <header className="topnav"><div className="topnav-inner"><Brand to="/library" /><span className="grow" />
        <button className="btn btn-sm btn-ghost" onClick={async () => { await save(true); nav("/library"); }}>Skip for now</button></div></header>
      <div className="page-narrow stack gap-24">
        <ol className="row gap-8" style={{ listStyle: "none", padding: 0, margin: 0 }} aria-label="Steps">
          {names.map((n, i) => <li key={n} className="grow stack gap-8"><div className="steps"><span className={i < step ? "done" : i === step ? "cur" : ""} /></div><span className={`small ${i === step ? "" : "muted"}`} style={{ fontWeight: 700 }}>{n}</span></li>)}
        </ol>
        {err && <ErrorBox error={err} />}
        {step === 0 && <div className="stack gap-16">
          <h1>What are you studying for?</h1>
          <p className="muted">This sets the default explanation level. You can change it on any section.</p>
          <div className="stack gap-8" role="radiogroup" aria-label="Goal">
            {goals.map((g) => (
              <button key={g.id} className="option" role="radio" aria-checked={goal === g.id} onClick={() => setGoal(g.id)}>
                <span className="stack gap-4"><span>{g.title} {g.pro && !canExam && <span className="badge badge-accent">Pro for exam level</span>}</span><span className="small muted" style={{ fontWeight: 500 }}>{g.body}</span></span>
              </button>))}
          </div>
          <div className="row gap-12"><button className="btn btn-primary" onClick={() => setStep(1)}>Continue</button></div>
        </div>}
        {step === 1 && <div className="stack gap-16">
          <h1>How much time per day?</h1>
          <p className="muted">We size each session and schedule flashcard reviews around it.</p>
          <div className="seg" role="radiogroup" aria-label="Daily time">{paces.map((p) => <button key={p.m} role="radio" aria-checked={minutes === p.m} onClick={() => setMinutes(p.m)} style={{ padding: "12px 24px" }}>{p.label}</button>)}</div>
          <label className="row gap-12" style={{ cursor: "pointer" }}><input type="checkbox" checked={reminders} onChange={(e) => setReminders(e.target.checked)} style={{ width: 20, height: 20 }} /><span><strong>Daily reminder</strong><br /><span className="small muted">An in-app nudge when cards are due.</span></span></label>
          <div className="row gap-12"><button className="btn btn-secondary" onClick={() => setStep(0)}>Back</button><button className="btn btn-primary" disabled={busy} onClick={async () => { await save(false); setStep(2); }}>{busy ? <Spinner /> : "Continue"}</button></div>
        </div>}
        {step === 2 && <div className="stack gap-16">
          <h1>Add your first book</h1>
          <p className="muted">PDF up to {me?.usage?.plan?.limits?.max_mb ?? 100} MB. Text and scanned books both work.</p>
          <UploadBox onDone={async (book) => { await save(true); nav(`/books/${book.id}/structure`); }} />
          <div className="row gap-12"><button className="btn btn-secondary" onClick={() => setStep(1)}>Back</button><button className="btn btn-ghost" onClick={async () => { await save(true); nav("/library"); }}>I'll do this later</button></div>
        </div>}
      </div>
    </div>
  );
}
