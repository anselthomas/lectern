import { useState } from "react";
import { Link } from "react-router-dom";
import { Brand } from "../components";
import { useMe } from "../state";

const features = [
  { title: "Chapters found for you", body: "Reads the bookmarks or contents page and maps every chapter to its pages. Fix anything before you start." },
  { title: "Three explanation levels", body: "Simple, Standard or Exam. Switch on any section when a paragraph doesn't click." },
  { title: "A tutor that stays in the book", body: "Ask anything. Answers come only from your PDF, with the page they came from." },
  { title: "Explain it back", body: "Put the idea in your own words and get feedback on what you got and what you missed." },
  { title: "Quizzes graded for the idea", body: "Multiple choice and short answers, marked for understanding rather than exact wording." },
  { title: "Spaced review", body: "Missed questions and key terms come back as flashcards, scheduled by FSRS right before you'd forget." },
];
const loop = [
  ["01", "Chapter map", "See the sections, key ideas and time it takes."],
  ["02", "Pre-question", "Say what you already know so lessons start at the right level."],
  ["03", "Lessons", "Short sections in plain words, each with quick checks."],
  ["04", "Explain it back", "Teach the idea back in 2–4 sentences."],
  ["05", "Chapter quiz", "Ten questions across every section."],
  ["06", "Flashcards", "Misses turn into cards automatically."],
  ["07", "Review", "A few minutes a day keeps it fresh."],
  ["08", "Final test", "A cumulative test weighted to your weak spots."],
];
const faqs = [
  ["What kinds of PDFs work?", "Textbooks, manuals and long reports. Text PDFs work on every plan; scanned PDFs (photos of pages) need Pro because we run OCR on them."],
  ["Does my book get sent to an AI all at once?", "No. Lectern reads one chapter or section at a time, and the tutor only sees the few passages that match your question."],
  ["How are page citations checked?", "Every citation must point to a page we actually sent to the model; anything else is dropped. You can open the page and report a wrong citation."],
  ["Who can see my books?", "Only you. Files are stored privately and encrypted, and every request is checked against your account."],
];

export default function Landing() {
  const { me } = useMe();
  const [yearly, setYearly] = useState(false);
  const [open, setOpen] = useState<number | null>(0);
  const start = me ? "/library" : "/signup";
  return (
    <div style={{ background: "#fff" }}>
      <header className="topnav" style={{ position: "static" }}>
        <div className="topnav-inner">
          <Brand />
          <nav className="navlinks hide-sm" aria-label="Sections">
            <a href="#how">How it works</a><a href="#features">Features</a><a href="#pricing">Pricing</a><a href="#faq">FAQ</a>
          </nav>
          <span className="grow" />
          {me ? <Link className="btn btn-sm btn-primary" to="/library">Open library</Link> : <>
            <Link className="btn btn-sm btn-ghost" to="/signin">Sign in</Link>
            <Link className="btn btn-sm btn-primary" to="/signup">Start free</Link>
          </>}
        </div>
      </header>
      <section className="page" style={{ paddingTop: 0 }}>
        <div className="hero">
          <div className="stack gap-24">
            <span className="eyebrow">For textbooks, manuals and long PDFs</span>
            <h1>Turn any book into a course you actually finish.</h1>
            <p className="reading" style={{ fontSize: 20 }}>Upload a PDF. Lectern finds the chapters, teaches them one at a time in plain words, checks what you kept, and brings back what you missed — every answer cited to the page.</p>
            <div className="row gap-12 wrap">
              <Link className="btn btn-primary" to={start}>Upload your first book</Link>
              <a className="btn btn-secondary" href="#how">See how it works</a>
            </div>
            <span className="small muted">Free for one book. No card needed.</span>
          </div>
          <div className="card stack gap-16" style={{ boxShadow: "0 24px 64px rgba(18,21,28,.10)" }}>
            <div className="row between"><span className="mono muted">Section 1.2 · pp. 8–13</span><div className="seg" role="presentation"><button>Simple</button><button aria-checked="true">Standard</button><button>Exam</button></div></div>
            <h2>Units and standards</h2>
            <p className="reading" style={{ fontSize: 17 }}>Every measurement is a number <strong>and</strong> a unit. The SI system picks seven base units — the metre, kilogram and second among them — and builds everything else from those.</p>
            <div className="soft stack gap-8"><span className="eyebrow">Quick check</span><strong>Which of these is an SI base unit?</strong>
              <div className="option" aria-checked="true"><span className="key">A</span>Kilogram</div><div className="option"><span className="key">B</span>Newton</div></div>
            <div className="row gap-8"><span className="small muted">Tutor:</span><span className="small">A newton is derived: kg·m/s².</span><span className="chip">p. 10</span></div>
          </div>
        </div>
      </section>
      <section id="how" style={{ background: "var(--bg)" }}>
        <div className="page stack gap-24">
          <div className="stack gap-8"><span className="eyebrow">How it works</span><h2>From PDF to a chapter-by-chapter course in three steps.</h2></div>
          <div className="feature-grid">
            {[["01", "Upload the book", "Drop in a textbook, manual or scanned PDF. Large files are fine — Lectern never sends the whole book to a model at once."],
              ["02", "Confirm the chapters", "It reads the bookmarks or contents page, maps every chapter to its pages, and lets you fix anything before you start."],
              ["03", "Learn one chapter at a time", "Each chapter opens with a map, teaches in short sections, and ends with a quiz. Missed ideas come back as flashcards."]].map(([n, t, b]) => (
              <div key={n} className="card stack gap-8"><span className="mono muted">{n}</span><h3>{t}</h3><p className="muted" style={{ lineHeight: 1.6 }}>{b}</p></div>))}
          </div>
        </div>
      </section>
      <section id="features" className="page stack gap-24">
        <div className="stack gap-8"><span className="eyebrow">Features</span><h2>Built for practice, not re-reading.</h2></div>
        <div className="feature-grid">{features.map((f) => <div key={f.title} className="card stack gap-8"><h3>{f.title}</h3><p className="muted" style={{ lineHeight: 1.6 }}>{f.body}</p></div>)}</div>
        <div className="stack gap-8" style={{ marginTop: 24 }}><span className="eyebrow">The learning loop</span><h2>Every chapter runs the same eight steps.</h2></div>
        <div className="loop-grid">{loop.map(([n, t, b]) => <div key={n} className="card-sm stack gap-4"><span className="mono muted">{n}</span><strong>{t}</strong><span className="small muted">{b}</span></div>)}</div>
      </section>
      <section id="pricing" style={{ background: "var(--bg)" }}>
        <div className="page stack gap-24">
          <div className="row between wrap gap-16">
            <div className="stack gap-8"><span className="eyebrow">Pricing</span><h2>Start with one book. Upgrade when you need a shelf.</h2></div>
            <div className="seg" role="radiogroup" aria-label="Billing period">
              <button role="radio" aria-checked={!yearly} onClick={() => setYearly(false)}>Monthly</button>
              <button role="radio" aria-checked={yearly} onClick={() => setYearly(true)}>Yearly</button>
            </div>
          </div>
          <div className="price-grid">
            <Plan name="Free" blurb="Try the full loop on one book." price="$0" items={["1 book", "Lessons, quizzes and flashcards", "Tutor chat with page citations"]} cta="Start free" to={start} />
            <Plan name="Pro" blurb="For students and self-learners." price={yearly ? "$89" : "$9.99"} period={yearly ? "/ year" : "/ month"} popular
              items={["Unlimited books", "Scanned PDFs and complex layouts", "Exam-level explanations and final tests", "Progress sync across devices"]} cta="Get Pro" to={start} />
            <Plan name="Teams" blurb="For classes, bootcamps and training." price={yearly ? "$80" : "$8"} period={yearly ? "per seat / year" : "per seat / month"}
              items={["Everything in Pro", "Shared course library", "Learner progress for instructors", "SSO and invoicing"]} cta="Talk to us" to="/help" />
          </div>
        </div>
      </section>
      <section id="faq" className="page-narrow stack gap-16">
        <span className="eyebrow">Questions</span>
        {faqs.map(([q, a], i) => (
          <div key={q} className="card-sm">
            <button className="row between" style={{ width: "100%", background: "none", border: 0, padding: 0, cursor: "pointer", fontWeight: 800, fontSize: 16, textAlign: "left" }}
              aria-expanded={open === i} onClick={() => setOpen(open === i ? null : i)}>{q}<span aria-hidden="true">{open === i ? "−" : "+"}</span></button>
            {open === i && <p className="muted" style={{ marginTop: 10, lineHeight: 1.6 }}>{a}</p>}
          </div>))}
      </section>
      <section style={{ background: "var(--ink)", color: "#fff" }}>
        <div className="page row between wrap gap-24">
          <h2 style={{ color: "#fff" }}>That book on your shelf? Start chapter one tonight.</h2>
          <Link className="btn btn-primary" to={start}>Upload a PDF</Link>
        </div>
      </section>
      <footer className="page row between wrap gap-16 small muted">
        <Brand />
        <div className="row gap-16 wrap"><Link to="/privacy">Privacy</Link><Link to="/terms">Terms</Link><Link to="/refunds">Refunds</Link><Link to="/help">Help & contact</Link></div>
        <span>© 2026 Lectern</span>
      </footer>
    </div>
  );
}

function Plan({ name, blurb, price, period, items, cta, to, popular }: { name: string; blurb: string; price: string; period?: string; items: string[]; cta: string; to: string; popular?: boolean }) {
  return (
    <div className="card stack gap-16" style={popular ? { borderColor: "var(--accent)", boxShadow: "0 0 0 2px var(--accent-soft-2)" } : undefined}>
      <div className="row between"><h3>{name}</h3>{popular && <span className="badge badge-accent">Most popular</span>}</div>
      <span className="muted">{blurb}</span>
      <div className="row gap-8" style={{ alignItems: "baseline" }}><span style={{ fontSize: 36, fontWeight: 800 }}>{price}</span>{period && <span className="muted small">{period}</span>}</div>
      <ul className="stack gap-8" style={{ margin: 0, paddingLeft: 20, lineHeight: 1.5 }}>{items.map((i) => <li key={i}>{i}</li>)}</ul>
      <Link className={`btn ${popular ? "btn-primary" : "btn-secondary"}`} to={to}>{cta}</Link>
    </div>
  );
}
