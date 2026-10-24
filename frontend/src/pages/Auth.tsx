import { FormEvent, ReactNode, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { confirmPassword, confirmSignUp, forgotPassword, friendlyError, resendCode, signIn, signUp } from "../auth";
import { Brand, Spinner } from "../components";
import { useMe } from "../state";

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="row wrap" style={{ minHeight: "100vh", alignItems: "stretch" }}>
      <aside className="hide-sm stack gap-24" style={{ flex: "1 1 420px", background: "var(--ink)", color: "#fff", padding: 48, justifyContent: "space-between" }}>
        <Link to="/" className="brand" style={{ color: "#fff" }}><span className="brand-mark">L</span>Lectern</Link>
        <div className="stack gap-16">
          <h1 style={{ color: "#fff" }}>One chapter at a time, every answer tied to the page.</h1>
          <ul className="stack gap-8" style={{ margin: 0, paddingLeft: 20, lineHeight: 1.6, color: "#c9ced6" }}>
            <li>Chapters detected from your PDF automatically</li>
            <li>Lessons, quizzes and flashcards per chapter</li>
            <li>Free for your first book</li>
          </ul>
        </div>
        <span className="small" style={{ color: "#9aa1ad" }}>© 2026 Lectern</span>
      </aside>
      <main style={{ flex: "1 1 480px", display: "grid", placeItems: "center", padding: 24, background: "#fff" }}>
        <div className="stack gap-24" style={{ width: "100%", maxWidth: 400 }}>
          <div className="row" style={{ display: "none" }}><Brand /></div>
          {children}
        </div>
      </main>
    </div>
  );
}

function Field({ id, label, type, ...props }: { id: string; label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  // Password fields get a Show button: look-alike characters (l and I, O and 0) are easy to mistype from a message.
  const [shown, setShown] = useState(false);
  const input = <input id={id} className="input" type={type === "password" && shown ? "text" : type} {...props}
    {...(type === "password" ? { autoCapitalize: "none", autoCorrect: "off", spellCheck: false, style: { paddingRight: 64, fontFamily: shown ? "var(--mono)" : undefined } } : {})} />;
  return <div className="field"><label htmlFor={id}>{label}</label>
    {type === "password" ? <div style={{ position: "relative" }}>{input}
      <button type="button" className="link-btn small" aria-pressed={shown} aria-label={shown ? "Hide password" : "Show password"}
        style={{ position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)" }} onClick={() => setShown(!shown)}>{shown ? "Hide" : "Show"}</button></div> : input}</div>;
}

export function SignIn() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const { refresh, me } = useMe();
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const next = params.get("next") || "/library";
  useEffect(() => { if (me) nav(next, { replace: true }); }, [me]);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      await signIn(email, password);
      await refresh();
      nav(next, { replace: true });
    } catch (e: any) {
      if (e?.code === "UserNotConfirmedException") { await resendCode(email).catch(() => undefined); nav(`/verify?email=${encodeURIComponent(email)}`); return; }
      setErr(friendlyError(e));
    } finally { setBusy(false); }
  };
  return (
    <Shell>
      <div className="seg" role="tablist"><Link to="/signup" className="btn btn-sm btn-ghost" role="tab">Create account</Link><button role="tab" aria-checked="true" aria-selected="true">Sign in</button></div>
      <div className="stack gap-8"><h2>Welcome back</h2><span className="muted">Pick up where you left off.</span></div>
      <form className="stack gap-16" onSubmit={submit} noValidate>
        {err && <div className="alert alert-error" role="alert">{err}</div>}
        {params.get("verified") && !err && <div className="alert alert-ok" role="status">Email verified. Sign in to continue.</div>}
        <Field id="email" label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <Field id="password" label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <Link to={`/forgot?email=${encodeURIComponent(email)}`} className="small" style={{ alignSelf: "flex-end" }}>Forgot password?</Link>
        <button className="btn btn-primary" disabled={busy || !email || !password}>{busy ? <Spinner /> : "Sign in"}</button>
      </form>
      <span className="small muted">By continuing you agree to the <Link to="/terms">Terms</Link> and <Link to="/privacy">Privacy Policy</Link>.</span>
    </Shell>
  );
}

export function SignUp() {
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const strong = password.length >= 8 && /\d/.test(password) && /[a-z]/.test(password);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      await signUp(name, email, password);
      nav(`/verify?email=${encodeURIComponent(email)}`);
    } catch (e) { setErr(friendlyError(e)); } finally { setBusy(false); }
  };
  return (
    <Shell>
      <div className="seg" role="tablist"><button role="tab" aria-checked="true" aria-selected="true">Create account</button><Link to="/signin" className="btn btn-sm btn-ghost" role="tab">Sign in</Link></div>
      <div className="stack gap-8"><h2>Start with your first book</h2><span className="muted">Free for one book. No card needed.</span></div>
      <form className="stack gap-16" onSubmit={submit} noValidate>
        {err && <div className="alert alert-error" role="alert">{err}</div>}
        <Field id="name" label="Name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
        <Field id="email" label="Email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <Field id="password" label="Password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} aria-describedby="pw-hint" />
        <span id="pw-hint" className={`small ${password && !strong ? "field-error" : "muted"}`}>At least 8 characters, with a number and a lowercase letter.</span>
        <button className="btn btn-primary" disabled={busy || !name || !email || !strong}>{busy ? <Spinner /> : "Create account"}</button>
      </form>
      <span className="small muted">By continuing you agree to the <Link to="/terms">Terms</Link> and <Link to="/privacy">Privacy Policy</Link>.</span>
    </Shell>
  );
}

export function Verify() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const { refresh } = useMe();
  const email = params.get("email") ?? "";
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [wait, setWait] = useState(45);
  useEffect(() => { const t = setInterval(() => setWait((w) => Math.max(0, w - 1)), 1000); return () => clearInterval(t); }, []);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      await confirmSignUp(email, code);
      nav(`/signin?email=${encodeURIComponent(email)}&verified=1`, { replace: true });
    } catch (e) { setErr(friendlyError(e)); } finally { setBusy(false); }
  };
  return (
    <Shell>
      <div className="stack gap-8"><h2>Verify your email</h2><span className="muted">Enter the 6-digit code we sent to <strong>{email}</strong>.</span></div>
      <form className="stack gap-16" onSubmit={submit}>
        {err && <div className="alert alert-error" role="alert">{err}</div>}
        {info && <div className="alert alert-ok" role="status">{info}</div>}
        <Field id="code" label="Verification code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
        <button className="btn btn-primary" disabled={busy || code.length !== 6}>{busy ? <Spinner /> : "Verify"}</button>
      </form>
      <span className="small muted">Wrong address? <Link to="/signup">Change email</Link> · {wait > 0 ? `Resend code in 0:${String(wait).padStart(2, "0")}` :
        <button className="link-btn" onClick={() => resendCode(email).then(() => { setInfo("New code sent."); setWait(45); }).catch((e) => setErr(friendlyError(e)))}>Resend code</button>}</span>
    </Shell>
  );
}

export function Forgot() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [stage, setStage] = useState<"ask" | "reset" | "done">("ask");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const strong = password.length >= 8 && /\d/.test(password) && /[a-z]/.test(password);
  const send = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try { await forgotPassword(email); setStage("reset"); } catch (e) { setErr(friendlyError(e)); } finally { setBusy(false); }
  };
  const reset = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try { await confirmPassword(email, code, password); setStage("done"); } catch (e) { setErr(friendlyError(e)); } finally { setBusy(false); }
  };
  return (
    <Shell>
      {stage === "ask" && <>
        <div className="stack gap-8"><h2>Reset your password</h2><span className="muted">Enter your account email and we'll send a reset code.</span></div>
        <form className="stack gap-16" onSubmit={send}>
          {err && <div className="alert alert-error" role="alert">{err}</div>}
          <Field id="email" label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <button className="btn btn-primary" disabled={busy || !email}>{busy ? <Spinner /> : "Send reset code"}</button>
          <Link to="/signin" className="small">Back to sign in</Link>
        </form>
      </>}
      {stage === "reset" && <>
        <div className="stack gap-8"><h2>Choose a new password</h2><span className="muted">If an account exists for {email}, a code is on its way. Check spam if it doesn't arrive.</span></div>
        <form className="stack gap-16" onSubmit={reset}>
          {err && <div className="alert alert-error" role="alert">{err}</div>}
          <Field id="code" label="Reset code" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
          <Field id="pw" label="New password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <Field id="pw2" label="Confirm password" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} aria-invalid={!!confirm && confirm !== password} />
          {password && <span className={`small ${strong ? "" : "field-error"}`} style={strong ? { color: "var(--ok)" } : undefined}>{strong ? "Strong password" : "At least 8 characters, with a number and a lowercase letter."}</span>}
          <button className="btn btn-primary" disabled={busy || !code || !strong || password !== confirm}>{busy ? <Spinner /> : "Update password"}</button>
        </form>
      </>}
      {stage === "done" && <div className="stack gap-16">
        <h2>Password updated</h2><span className="muted">Sign in with your new password.</span>
        <button className="btn btn-primary" onClick={() => nav(`/signin?email=${encodeURIComponent(email)}`)}>Sign in</button>
      </div>}
    </Shell>
  );
}
