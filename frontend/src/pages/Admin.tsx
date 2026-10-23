import { ReactNode, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ErrorBox, Loading } from "../components";
import { useApi } from "../state";

const usd = (x: number | null | undefined, d = 2) => (x == null ? "—" : `$${Number(x).toFixed(x !== 0 && Math.abs(x) < 0.01 ? 4 : d)}`);
const num = (x: number | null | undefined) => (x == null ? "—" : Number(x).toLocaleString());
const ago = (iso?: string | null) => {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
};

type Col<T> = { key: string; label: string; render?: (r: T) => ReactNode; align?: "right" };

/** A table on desktop; labelled cards on phones (see .data-table in styles.css). */
function DataTable<T extends Record<string, any>>({ cols, rows, empty = "Nothing yet." }: { cols: Col<T>[]; rows: T[]; empty?: string }) {
  if (!rows.length) return <p className="muted small">{empty}</p>;
  return (
    <div className="data-table-wrap">
      <table className="table data-table">
        <thead><tr>{cols.map((c) => <th key={c.key} style={c.align ? { textAlign: c.align } : undefined}>{c.label}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => (
          <tr key={r.id ?? i}>{cols.map((c) => <td key={c.key} data-label={c.label} style={c.align ? { textAlign: c.align } : undefined}>{c.render ? c.render(r) : r[c.key] ?? "—"}</td>)}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return <div className="card-sm stack gap-4 grow" style={{ flexBasis: 160 }}><span className="label">{label}</span><strong style={{ fontSize: 24 }}>{value}</strong>{sub && <span className="small muted">{sub}</span>}</div>;
}

function Bars({ data, value, label }: { data: any[]; value: (d: any) => number; label: (d: any) => string }) {
  const max = Math.max(...data.map(value), 0.000001);
  return (
    <div className="stack gap-4">
      <div className="chart" role="img" aria-label="Daily chart">
        {data.map((d, i) => <div key={i} className="col" title={`${label(d)}: ${value(d)}`}><span className="b" style={{ height: `${(value(d) / max) * 100}%` }} /></div>)}
      </div>
      {data.length > 0 && <div className="row between tiny muted"><span>{label(data[0])}</span><span>{label(data[data.length - 1])}</span></div>}
    </div>
  );
}

const TABS = [["overview", "Overview"], ["users", "Users"], ["books", "Books"], ["learning", "Learning"], ["calls", "AI calls"], ["system", "System"]] as const;

export default function Admin() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "overview";
  const [days, setDays] = useState(30);
  return (
    <div className="page stack gap-24">
      <div className="row between wrap gap-12">
        <div className="stack gap-4"><h1>Admin</h1><span className="muted">Usage, learning and cost across every user</span></div>
        <div className="seg" role="radiogroup" aria-label="Period">{[1, 7, 30, 90].map((d) => <button key={d} role="radio" aria-checked={days === d} onClick={() => setDays(d)}>{d === 1 ? "24 h" : `${d} d`}</button>)}</div>
      </div>
      <nav className="seg wrap" role="tablist" aria-label="Admin sections" style={{ alignSelf: "flex-start" }}>
        {TABS.map(([k, l]) => <button key={k} role="tab" aria-checked={tab === k} aria-selected={tab === k} onClick={() => setParams({ tab: k })}>{l}</button>)}
      </nav>
      {tab === "overview" && <Overview days={days} />}
      {tab === "users" && <Users days={days} />}
      {tab === "books" && <Books />}
      {tab === "learning" && <Learning days={days} />}
      {tab === "calls" && <Calls />}
      {tab === "system" && <System />}
    </div>
  );
}

function Overview({ days }: { days: number }) {
  const { data: o, error, reload } = useApi<any>(`/admin/overview?days=${days}`, [days]);
  if (error) return <ErrorBox error={error} retry={() => reload()} />;
  if (!o) return <Loading />;
  const c = o.cost, a = o.activity;
  return (
    <div className="stack gap-24">
      <div className="row gap-12 wrap">
        <Tile label="Users" value={num(o.users.total)} sub={`${o.users.new} new · ${o.users.pro} Pro`} />
        <Tile label="Active" value={num(o.users.active_7d)} sub={`${o.users.active_1d} today · ${o.users.active_30d} in 30 d`} />
        <Tile label={`AI cost (${days} d)`} value={usd(c.period)} sub={`${num(c.calls)} calls · ${c.errors} errors`} />
        <Tile label="Projected month" value={usd(c.projected_month_total)} sub={`${usd(c.projected_month_ai)} AI + ${usd(c.fixed_monthly, 0)} infra`} />
      </div>
      <div className="row gap-12 wrap">
        <Tile label="Input tokens" value={num(c.tokens_in)} />
        <Tile label="Output tokens" value={num(c.tokens_out)} />
        <Tile label="Month to date (AI)" value={usd(c.month_to_date_ai)} />
        <Tile label="AI cost / active user / month" value={usd(c.per_active_user_30d)} sub={c.avg_latency_ms ? `avg latency ${(c.avg_latency_ms / 1000).toFixed(1)} s` : undefined} />
      </div>
      <div className="card stack gap-12"><h3>AI cost per day</h3><Bars data={o.daily} value={(d) => d.cost} label={(d) => d.day} /></div>
      <div className="row gap-24 wrap" style={{ alignItems: "flex-start" }}>
        <div className="card stack gap-12 grow" style={{ flexBasis: 380 }}><h3>Cost by feature</h3>
          <DataTable rows={o.by_feature} cols={[{ key: "feature", label: "Feature" }, { key: "calls", label: "Calls", align: "right", render: (r) => num(r.calls) },
            { key: "tokens_in", label: "In", align: "right", render: (r) => num(r.tokens_in) }, { key: "tokens_out", label: "Out", align: "right", render: (r) => num(r.tokens_out) },
            { key: "cost", label: "Cost", align: "right", render: (r) => usd(r.cost) }]} /></div>
        <div className="card stack gap-12 grow" style={{ flexBasis: 380 }}><h3>Learning activity ({days} d)</h3>
          <DataTable rows={[["Uploads", a.uploads], ["Chapters started", a.chapters_started], ["Sections completed", a.sections_completed],
            ["Explain-backs", a.explains], ["Quizzes", `${a.quizzes}${a.quiz_avg != null ? ` · avg ${a.quiz_avg}%` : ""}`], ["Final tests", a.final_tests],
            ["Cards reviewed", a.cards_reviewed], ["Tutor messages", a.tutor_messages], ["Voice answers", a.voice_clips], ["Sign-ups", a.signups]].map(([k, v]) => ({ k, v }))}
            cols={[{ key: "k", label: "Action" }, { key: "v", label: "Count", align: "right" }]} /></div>
      </div>
      <div className="card stack gap-12"><h3>By model call type</h3>
        <DataTable rows={o.by_kind} cols={[{ key: "kind", label: "Call" }, { key: "model", label: "Model" }, { key: "tier", label: "Tier" },
          { key: "calls", label: "Calls", align: "right", render: (r) => num(r.calls) }, { key: "tokens_in", label: "In", align: "right", render: (r) => num(r.tokens_in) },
          { key: "tokens_out", label: "Out", align: "right", render: (r) => num(r.tokens_out) }, { key: "avg_latency_ms", label: "Avg latency", align: "right", render: (r) => r.avg_latency_ms ? `${(r.avg_latency_ms / 1000).toFixed(1)} s` : "—" },
          { key: "cost", label: "Cost", align: "right", render: (r) => usd(r.cost) }]} /></div>
      <div className="row gap-12 wrap">
        <Tile label="Library" value={`${num(o.library.books)} books`} sub={`${num(o.library.pages)} pages · ${o.library.chapters_built}/${o.library.chapters_total} chapters built`} />
        <Tile label="Content" value={`${num(o.library.lessons)} lessons`} sub={`${num(o.library.cards)} flashcards`} />
        <Tile label="Failed jobs" value={o.failed_jobs} sub={<Link to="/admin?tab=system">System →</Link>} />
      </div>
      <p className="small muted">Prices used: Nova 2 Lite ${c.prices.text.standard[0]}/{c.prices.text.standard[1]} per 1M tokens (flex ${c.prices.text.flex[0]}/{c.prices.text.flex[1]}), Titan embeddings ${c.prices.embed_per_m}/1M, Transcribe ${c.prices.transcribe_per_min}/min. Infra is a fixed estimate.</p>
    </div>
  );
}

function Users({ days }: { days: number }) {
  const { data, error } = useApi<any[]>(`/admin/users?days=${days}`, [days]);
  const [q, setQ] = useState("");
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  const rows = data.filter((u) => !q || `${u.email} ${u.name ?? ""}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="card stack gap-12">
      <div className="row between wrap gap-8"><h3>{data.length} users</h3><input className="input" style={{ maxWidth: 280, height: 40 }} placeholder="Filter by email or name" aria-label="Filter users" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      <DataTable rows={rows} cols={[
        { key: "email", label: "User", render: (u) => <Link to={`/admin/users/${u.id}`}>{u.email}</Link> },
        { key: "plan_id", label: "Plan", render: (u) => <span className="row gap-4 wrap"><span className="badge badge-muted">{u.plan_id}</span>{u.is_admin && <span className="badge badge-accent">admin</span>}</span> },
        { key: "last_seen_at", label: "Last seen", render: (u) => ago(u.last_seen_at) },
        { key: "books", label: "Books", align: "right" },
        { key: "chapters_mastered", label: "Mastered", align: "right" },
        { key: "sections_done", label: "Sections", align: "right" },
        { key: "quiz_avg", label: "Quiz avg", align: "right", render: (u) => (u.quiz_avg != null ? `${u.quiz_avg}%` : "—") },
        { key: "study_minutes", label: "Study", align: "right", render: (u) => `${u.study_minutes} min` },
        { key: "tutor_messages", label: "Tutor", align: "right" },
        { key: "tokens", label: `Tokens (${days} d)`, align: "right", render: (u) => `${num(u.tokens_in)} / ${num(u.tokens_out)}` },
        { key: "cost_period", label: `Cost (${days} d)`, align: "right", render: (u) => usd(u.cost_period) },
        { key: "cost_total", label: "Cost (all)", align: "right", render: (u) => usd(u.cost_total) },
      ]} />
    </div>
  );
}

export function AdminUser() {
  const { userId } = useParams();
  const { data, error } = useApi<any>(`/admin/users/${userId}`);
  if (error) return <div className="page"><ErrorBox error={error} /></div>;
  if (!data) return <Loading />;
  const u = data.user;
  return (
    <div className="page stack gap-24">
      <nav className="small muted"><Link to="/admin?tab=users">Admin · Users</Link> / {u.email}</nav>
      <div className="stack gap-4"><h1 style={{ wordBreak: "break-word" }}>{u.name || u.email}</h1>
        <span className="muted">{u.email} · {u.plan} plan{u.is_admin ? " · admin" : ""} · joined {new Date(u.created_at).toLocaleDateString()} · last seen {ago(u.last_seen_at)} · default level {u.level_default} · {u.daily_minutes} min/day</span></div>
      <div className="card stack gap-12"><h3>AI usage by feature (30 d)</h3>
        <DataTable rows={data.by_feature} cols={[{ key: "feature", label: "Feature" }, { key: "calls", label: "Calls", align: "right" },
          { key: "tokens_in", label: "In", align: "right", render: (r) => num(r.tokens_in) }, { key: "tokens_out", label: "Out", align: "right", render: (r) => num(r.tokens_out) },
          { key: "cost", label: "Cost", align: "right", render: (r) => usd(r.cost) }]} /></div>
      {data.books.map((b: any) => (
        <div key={b.id} className="card stack gap-12">
          <div className="row between wrap gap-8"><h3>{b.title}</h3><span className="small muted">{b.pages} pages · {b.structure_source ?? "no structure"} · {b.status} · AI cost {usd(b.cost)}</span></div>
          <DataTable rows={b.chapters.filter((c: any) => c.kind === "chapter" || c.kind === "appendix")} cols={[
            { key: "n", label: "#" }, { key: "title", label: "Chapter" }, { key: "status", label: "Build" },
            { key: "progress", label: "Sections", render: (c) => `${c.sections_done}/${c.sections}` },
            { key: "self_rating", label: "Self-rating", render: (c) => c.self_rating ?? "—" },
            { key: "explain", label: "Explain", render: (c) => (c.explain_total ? `${c.explain_met}/${c.explain_total}` : "—") },
            { key: "quiz_best", label: "Best quiz", render: (c) => (c.quiz_best != null ? `${Math.round(c.quiz_best * 100)}%` : "—") },
            { key: "mastered", label: "Mastered", render: (c) => (c.mastered ? "✓" : "") },
            { key: "cost", label: "Cost", align: "right", render: (c) => usd(c.cost) }]} />
        </div>))}
      <div className="card stack gap-12"><h3>Recent activity</h3>
        <DataTable rows={data.events} cols={[{ key: "created_at", label: "When", render: (e) => ago(e.created_at) }, { key: "type", label: "Event" },
          { key: "chapter", label: "Chapter", render: (e) => e.chapter ?? "—" },
          { key: "props", label: "Details", render: (e) => <span className="small mono" style={{ wordBreak: "break-word" }}>{Object.entries(e.props || {}).filter(([k]) => k !== "title").map(([k, v]) => `${k}=${v}`).join(" · ")}</span> }]} /></div>
    </div>
  );
}

function Books() {
  const { data, error } = useApi<any[]>("/admin/books");
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  return (
    <div className="card stack gap-12"><h3>{data.length} books</h3>
      <DataTable rows={data} cols={[{ key: "title", label: "Book" }, { key: "email", label: "Owner" }, { key: "pages", label: "Pages", align: "right" },
        { key: "kind", label: "Type" }, { key: "structure_source", label: "Chapters from", render: (b) => b.structure_source ?? "—" },
        { key: "built", label: "Built", render: (b) => `${b.chapters_built}/${b.chapters}` }, { key: "status", label: "Status" },
        { key: "embedded_chunks", label: "Indexed", align: "right", render: (b) => `${num(b.embedded_chunks)} (${b.embed_status})` },
        { key: "cost", label: "AI cost", align: "right", render: (b) => usd(b.cost) }, { key: "created_at", label: "Added", render: (b) => ago(b.created_at) }]} /></div>
  );
}

function Learning({ days }: { days: number }) {
  const { data: l, error } = useApi<any>(`/admin/learning?days=${days}`, [days]);
  if (error) return <ErrorBox error={error} />;
  if (!l) return <Loading />;
  const top = Math.max(1, ...l.funnel.map((f: any) => f.users));
  return (
    <div className="stack gap-24">
      <div className="card stack gap-12"><h3>Learner funnel ({days} d)</h3>
        {l.funnel.map((f: any) => (
          <div key={f.step} className="stack gap-4"><div className="row between small"><span>{f.step}</span><strong>{f.users}</strong></div>
            <div className="bar"><span style={{ width: `${(f.users / top) * 100}%` }} /></div></div>))}
      </div>
      <div className="card stack gap-12"><h3>Most-studied chapters</h3>
        <DataTable rows={l.top_chapters} cols={[{ key: "title", label: "Chapter" }, { key: "book", label: "Book" }, { key: "learners", label: "Learners", align: "right" },
          { key: "starts", label: "Starts", align: "right" }, { key: "sections_completed", label: "Sections done", align: "right" },
          { key: "tutor_questions", label: "Tutor Qs", align: "right" }, { key: "quiz_avg", label: "Quiz avg", align: "right", render: (r) => (r.quiz_avg != null ? `${r.quiz_avg}%` : "—") }]} /></div>
      <div className="row gap-24 wrap" style={{ alignItems: "flex-start" }}>
        <div className="card stack gap-12 grow" style={{ flexBasis: 380 }}><h3>Top topics (sections completed)</h3>
          <DataTable rows={l.top_topics} cols={[{ key: "section", label: "§" }, { key: "topic", label: "Topic" }, { key: "completions", label: "Done", align: "right" }, { key: "learners", label: "Learners", align: "right" }]} /></div>
        <div className="card stack gap-12 grow" style={{ flexBasis: 280 }}><h3>Quiz scores</h3>
          <DataTable rows={l.quiz_buckets} cols={[{ key: "range", label: "Score" }, { key: "n", label: "Attempts", align: "right" }]} empty="No quizzes yet." />
          <span className="small muted">Explain-backs: {l.explain.n}{l.explain.avg_points != null ? ` · avg ${l.explain.avg_points}% of key points` : ""}</span>
          <span className="small muted">Default levels: {l.levels.map((x: any) => `${x.level} ${x.users}`).join(" · ")}</span></div>
      </div>
    </div>
  );
}

function Calls() {
  const [errors, setErrors] = useState(false);
  const { data, error } = useApi<any[]>(`/admin/calls?limit=150&errors_only=${errors}`, [errors]);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  return (
    <div className="card stack gap-12">
      <div className="row between wrap gap-8"><h3>Recent model calls</h3>
        <label className="row gap-8 small"><input type="checkbox" checked={errors} onChange={(e) => setErrors(e.target.checked)} />Errors only</label></div>
      <DataTable rows={data} empty={errors ? "No errors." : "No calls yet."} cols={[{ key: "created_at", label: "When", render: (r) => ago(r.created_at) },
        { key: "email", label: "User", render: (r) => r.email ?? "—" }, { key: "feature", label: "Feature" }, { key: "kind", label: "Call" }, { key: "tier", label: "Tier" },
        { key: "tokens", label: "Tokens in/out", align: "right", render: (r) => (r.kind === "transcribe" ? `${r.units ?? 0} s audio` : `${num(r.tokens_in)} / ${num(r.tokens_out)}${r.calls > 1 ? ` (${r.calls} calls)` : ""}`) },
        { key: "latency_ms", label: "Latency", align: "right", render: (r) => (r.latency_ms ? `${(r.latency_ms / 1000).toFixed(1)} s` : "—") },
        { key: "cost_usd", label: "Cost", align: "right", render: (r) => usd(r.cost_usd, 4) },
        { key: "ok", label: "Result", render: (r) => (r.ok ? <span className="badge badge-ok">ok</span> : <span className="badge badge-bad" title={r.error}>error</span>) },
        { key: "chapter", label: "Where", render: (r) => <span className="small">{r.chapter ?? r.book ?? "—"}</span> }]} />
    </div>
  );
}

function System() {
  const { data, error, reload } = useApi<any>("/admin/system");
  if (error) return <ErrorBox error={error} retry={() => reload()} />;
  if (!data) return <Loading />;
  return (
    <div className="stack gap-24">
      <div className="card stack gap-12"><h3>Jobs (7 d)</h3><DataTable rows={data.jobs} cols={[{ key: "type", label: "Job" }, { key: "status", label: "Status" }, { key: "n", label: "Count", align: "right" }]} /></div>
      <div className="card stack gap-12"><h3>Needs attention</h3><DataTable rows={data.attention} empty="Nothing stuck or failed." cols={[{ key: "what", label: "What" }, { key: "name", label: "Name" }, { key: "status", label: "Status" }]} /></div>
      <div className="card stack gap-12"><h3>Recent failed jobs</h3><DataTable rows={data.failures} empty="No failed jobs." cols={[{ key: "created_at", label: "When", render: (r) => ago(r.created_at) },
        { key: "type", label: "Job" }, { key: "attempts", label: "Tries", align: "right" }, { key: "error", label: "Error", render: (r) => <span className="small mono" style={{ wordBreak: "break-word" }}>{(r.error || "").split("\n").filter(Boolean).slice(-1)[0]}</span> }]} /></div>
    </div>
  );
}
