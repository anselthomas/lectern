import { ReactNode, useEffect, useRef, useState } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { api, apiBlobUrl } from "./api";
import { signOut } from "./auth";
import { useMe } from "./state";

export function Spinner({ large }: { large?: boolean }) {
  return <span className={`spinner${large ? " spinner-lg" : ""}`} role="status" aria-label="Loading" />;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="empty" style={{ minHeight: 240 }}>
      <Spinner large />
      <span className="muted">{label}</span>
    </div>
  );
}

export function ErrorBox({ error, retry }: { error: any; retry?: () => void }) {
  return (
    <div className="alert alert-error row gap-12 between wrap" role="alert">
      <span>{error?.message ?? String(error)}</span>
      {retry && <button className="btn btn-sm btn-secondary" onClick={retry}>Try again</button>}
    </div>
  );
}

export function Brand({ to = "/" }: { to?: string }) {
  return (
    <Link to={to} className="brand" aria-label="Lectern home">
      <span className="brand-mark" aria-hidden="true">L</span><span className="brand-text">Lectern</span>
    </Link>
  );
}

const Icon = {
  bell: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.7 21a2 2 0 0 1-3.4 0" /></svg>,
  search: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>,
};

export function TopNav() {
  const { me } = useMe();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let alive = true;
    const load = () => api("/notifications").then((n) => alive && setUnread(n.unread)).catch(() => undefined);
    load();
    const t = setInterval(load, 30000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  useEffect(() => {
    const close = (e: MouseEvent) => menuRef.current && !menuRef.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const initials = (me?.name || me?.email || "?").split(/[\s@.]/).filter(Boolean).slice(0, 2).map((s: string) => s[0]?.toUpperCase()).join("");
  return (
    <header className="topnav">
      <div className="topnav-inner">
        <Brand to="/library" />
        <nav className="navlinks" aria-label="Main">
          <NavLink to="/library">Library</NavLink>
          <NavLink to="/review">Review</NavLink>
          <NavLink to="/progress" className={({ isActive }) => `hide-sm${isActive ? " active" : ""}`}>Progress</NavLink>
        </nav>
        <span className="grow" />
        <Link to="/search" className="icon-btn" aria-label="Search">{Icon.search}</Link>
        <Link to="/notifications" className="icon-btn" aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}>
          {Icon.bell}{unread > 0 && <span className="dot">{unread > 9 ? "9+" : unread}</span>}
        </Link>
        <div style={{ position: "relative" }} ref={menuRef}>
          <button className="icon-btn" aria-haspopup="menu" aria-expanded={open} aria-label="Account menu" onClick={() => setOpen(!open)}>
            <span className="avatar">{initials}</span>
          </button>
          {open && (
            <div className="menu" role="menu">
              <div style={{ padding: "10px 12px" }}>
                <div style={{ fontWeight: 800 }}>{me?.name || "Your account"}</div>
                <div className="small muted">{me?.email}</div>
                <div className="tiny" style={{ marginTop: 6 }}><span className="badge badge-accent">{me?.usage?.plan?.name} plan</span></div>
              </div>
              <hr className="divider" />
              <Link role="menuitem" to="/progress" onClick={() => setOpen(false)}>Progress</Link>
              <Link role="menuitem" to="/settings" onClick={() => setOpen(false)}>Settings & billing</Link>
              <Link role="menuitem" to="/help" onClick={() => setOpen(false)}>Help & contact</Link>
              <hr className="divider" />
              <button role="menuitem" onClick={() => { signOut(); nav("/"); window.location.reload(); }}>Sign out</button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

export function Modal({ children, onClose, wide, label }: { children: ReactNode; onClose: () => void; wide?: boolean; label: string }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? " modal-wide" : ""}`} role="dialog" aria-modal="true" aria-label={label}>{children}</div>
    </div>
  );
}

export function UpgradeModal({ message, onClose }: { message: string; onClose: () => void }) {
  const { me } = useMe();
  const pro = me?.usage?.plan;
  return (
    <Modal onClose={onClose} label="Upgrade to Pro">
      <div className="stack gap-16">
        <span className="eyebrow">Upgrade</span>
        <h2>{message}</h2>
        <ul className="stack gap-8" style={{ margin: 0, paddingLeft: 20, lineHeight: 1.6 }}>
          <li>Unlimited books, including scanned PDFs</li>
          <li>Exam-level explanations and final tests</li>
          <li>Your current book and progress stay exactly as they are</li>
        </ul>
        <p className="muted">$9.99 per month, or $89 yearly. {pro?.id === "free" ? "" : ""}</p>
        <div className="alert alert-info">Payments aren't switched on yet — this is a preview of the upgrade flow.</div>
        <div className="row gap-12 wrap">
          <button className="btn btn-primary" onClick={onClose}>Upgrade to Pro</button>
          <button className="btn btn-secondary" onClick={onClose}>Maybe later</button>
        </div>
      </div>
    </Modal>
  );
}

export function PageChip({ label, page, onOpen }: { label?: string | null; page?: number | null; onOpen?: (page: number) => void }) {
  if (!page) return null;
  return (
    <button type="button" className="chip" onClick={() => onOpen?.(page)} aria-label={`Open page ${label ?? page}`}>
      p. {label ?? page}
    </button>
  );
}

/** Source page viewer: the actual PDF page, rendered by the server. */
export function SourceViewer({ bookId, page, onClose, quote }: { bookId: string; page: number; onClose: () => void; quote?: string }) {
  const [n, setN] = useState(page);
  const [img, setImg] = useState<string | null>(null);
  const [meta, setMeta] = useState<any>(null);
  const [err, setErr] = useState<any>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [zoom, setZoom] = useState(100);
  useEffect(() => {
    let url: string | null = null;
    setImg(null); setErr(null); setSaved(null);
    api(`/books/${bookId}/pages/${n}`).then(setMeta).catch(setErr);
    apiBlobUrl(`/books/${bookId}/pages/${n}/image`).then((u) => { url = u; setImg(u); }).catch(setErr);
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [bookId, n]);
  const save = async (kind: "highlight" | "citation_report") => {
    await api(`/books/${bookId}/notes`, { body: { pdf_page: n, kind, quote: quote ?? null, text: kind === "citation_report" ? "Reported as a wrong citation" : null } });
    setSaved(kind === "highlight" ? "Saved to your notes." : "Thanks — we've logged this citation for review.");
  };
  return (
    <Modal onClose={onClose} wide label={`Source page ${meta?.label ?? n}`}>
      <div className="row between wrap gap-12" style={{ padding: "14px 20px", borderBottom: "1px solid var(--line)" }}>
        <button className="btn btn-sm btn-secondary" onClick={onClose}>← Back to lesson</button>
        <div className="row gap-8">
          <button className="btn btn-sm btn-secondary" disabled={n <= 1} onClick={() => setN(n - 1)} aria-label="Previous page">‹</button>
          <span className="mono">Page {meta?.label ?? n}{meta ? ` · PDF ${n} of ${meta.pages}` : ""}</span>
          <button className="btn btn-sm btn-secondary" disabled={!!meta && n >= meta.pages} onClick={() => setN(n + 1)} aria-label="Next page">›</button>
        </div>
        <div className="row gap-8">
          <button className="btn btn-sm btn-secondary" onClick={() => setZoom(Math.max(60, zoom - 20))} aria-label="Zoom out">−</button>
          <span className="mono">{zoom}%</span>
          <button className="btn btn-sm btn-secondary" onClick={() => setZoom(Math.min(200, zoom + 20))} aria-label="Zoom in">+</button>
        </div>
      </div>
      <div className="row wrap" style={{ alignItems: "flex-start" }}>
        <div style={{ flex: "3 1 480px", background: "var(--bg)", padding: 20, maxHeight: "72vh", overflow: "auto" }}>
          {err && <ErrorBox error={err} />}
          {!img && !err && <Loading label="Rendering page…" />}
          {img && <img src={img} alt={`Page ${meta?.label ?? n} of the book`} className="page-img" style={{ width: `${zoom}%`, maxWidth: "none" }} />}
        </div>
        <aside style={{ flex: "1 1 240px", padding: 20 }} className="stack gap-16">
          {meta?.chapter && <div><div className="label">Chapter</div><div style={{ fontWeight: 700 }}>{meta.chapter.n}. {meta.chapter.title}</div></div>}
          {quote && <div><div className="label">Cited from</div><p className="reading" style={{ fontSize: 15 }}>“{quote}”</p></div>}
          {saved && <div className="alert alert-ok" role="status">{saved}</div>}
          <button className="btn btn-sm btn-primary" onClick={() => save("highlight")}>Save page to notes</button>
          <button className="link-btn small" onClick={() => save("citation_report")}>Report a wrong citation</button>
        </aside>
      </div>
    </Modal>
  );
}

export function Toast({ text, onDone }: { text: string; onDone: () => void }) {
  useEffect(() => { const t = setTimeout(onDone, 3000); return () => clearTimeout(t); }, [onDone]);
  return <div className="toast" role="status">{text}</div>;
}

/** Renders **bold** inside model text without allowing HTML. */
export function Rich({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return <>{parts.map((p, i) => p.startsWith("**") && p.endsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong> : <span key={i}>{p}</span>)}</>;
}

export const coverColors = ["#3346D3", "#1F7A4D", "#9A4A06", "#2A2F3A", "#8A1C12", "#2836A8"];
export function Cover({ title, i = 0 }: { title: string; i?: number }) {
  const hash = [...title].reduce((a, c) => a + c.charCodeAt(0), i);
  return <div className="cover" style={{ background: coverColors[hash % coverColors.length] }} aria-hidden="true">{title.trim()[0]?.toUpperCase()}</div>;
}

const DAILY_PRESETS = [20, 60, 120, 240, 480];

export function formatMinutes(m: number) {
  if (m < 60) return `${m} min`;
  const h = m / 60;
  return `${Number.isInteger(h) ? h : h.toFixed(1)} h`;
}

/** Daily study time, from a short session to a full study day (max 12 h). Value is in minutes. */
export function DailyTimePicker({ value, onChange }: { value: number; onChange: (minutes: number) => void }) {
  const preset = DAILY_PRESETS.includes(value);
  const [custom, setCustom] = useState(!preset);
  const [hours, setHours] = useState(preset ? "" : String(+(value / 60).toFixed(2)));
  const commit = (raw: string) => {
    setHours(raw);
    const h = parseFloat(raw);
    if (h > 0) onChange(Math.round(Math.min(12, Math.max(0.25, h)) * 60));
  };
  return (
    <div className="stack gap-12">
      <div className="seg wrap" role="radiogroup" aria-label="Daily time">
        {DAILY_PRESETS.map((m) => (
          <button key={m} role="radio" aria-checked={!custom && value === m} style={{ padding: "12px 18px" }}
            onClick={() => { setCustom(false); onChange(m); }}>{formatMinutes(m)}</button>))}
        <button role="radio" aria-checked={custom} style={{ padding: "12px 18px" }} onClick={() => { setCustom(true); setHours(String(+(value / 60).toFixed(2))); }}>Custom</button>
      </div>
      {custom && (
        <div className="row gap-8">
          <input className="input mono" style={{ width: 110 }} type="number" min={0.25} max={12} step={0.25} aria-label="Hours per day"
            value={hours} onChange={(e) => commit(e.target.value)} />
          <span className="muted">hours a day (up to 12)</span>
        </div>
      )}
    </div>
  );
}
