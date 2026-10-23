import { Link } from "react-router-dom";
import { Brand } from "../components";
import { useMe } from "../state";

function Plain({ children }: { children: React.ReactNode }) {
  const { me } = useMe();
  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <header className="topnav"><div className="topnav-inner"><Brand to={me ? "/library" : "/"} /><span className="grow" />{me ? <Link to="/library" className="btn btn-sm btn-secondary">Library</Link> : <Link to="/signin" className="btn btn-sm btn-secondary">Sign in</Link>}</div></header>
      <div className="page-narrow stack gap-16">{children}</div>
    </div>
  );
}

const legal: Record<string, [string, string[]]> = {
  privacy: ["Privacy", [
    "Your PDFs, notes, progress and chat history belong to you. We store them privately and encrypted in AWS (Sydney region) and only use them to run your account.",
    "To teach and answer questions, we send short passages of your book — never the whole file — to Amazon Bedrock. Bedrock doesn't use them to train models.",
    "We don't sell your data or show ads. You can download everything or delete your account from Settings at any time.",
  ]],
  terms: ["Terms", [
    "Upload only books you have the right to use. Lectern is a study aid: generated lessons can contain mistakes, so check important facts against the cited pages.",
    "Free accounts include one book. Paid plans renew automatically until cancelled.",
  ]],
  refunds: ["Refunds", [
    "If Lectern isn't working for you, contact us within 14 days of a charge and we'll refund it in full.",
  ]],
};

export function Legal({ kind }: { kind: "privacy" | "terms" | "refunds" }) {
  const [title, paras] = legal[kind];
  return <Plain><h1>{title}</h1>{paras.map((p) => <p key={p} className="reading" style={{ fontSize: 17 }}>{p}</p>)}<span className="small muted">Last updated October 2026.</span></Plain>;
}

export function Help() {
  return (
    <Plain>
      <h1>Help & contact</h1>
      {[["My PDF says “Couldn't read”", "Check that it opens in a normal PDF reader. Scanned books need Pro (we run OCR on them). Password-protected files ask for the password once."],
        ["The chapters look wrong", "Open the book, choose “Edit chapters”, and rename, merge, split or fix page ranges. Lessons follow your outline."],
        ["A citation points to the wrong page", "Open the page from the citation and choose “Report a wrong citation”. It helps us improve."],
        ["How do flashcards get scheduled?", "With FSRS, a modern spaced-repetition algorithm. Change your target recall in Settings."]].map(([q, a]) => (
        <div key={q} className="card-sm stack gap-8"><strong>{q}</strong><span className="muted">{a}</span></div>))}
      <div className="card stack gap-8"><h3>Still stuck?</h3><span className="muted">Open an issue at <a href="https://github.com/anselthomas/lectern/issues" target="_blank" rel="noreferrer">github.com/anselthomas/lectern</a> with the book title and what you were doing.</span></div>
    </Plain>
  );
}

export function NotFound() {
  return (
    <Plain>
      <div className="card empty"><span className="mono muted">404</span><h1>This page isn't in the book</h1><p className="muted">The link may be old, or the page moved.</p><Link className="btn btn-strong" to="/">Go home</Link></div>
    </Plain>
  );
}
