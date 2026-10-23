import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorBox, Loading } from "../components";
import { useApi } from "../state";

function ago(iso: string) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

export default function Notifications() {
  const { data, error, reload } = useApi<any>("/notifications");
  if (error) return <div className="page-narrow"><ErrorBox error={error} /></div>;
  if (!data) return <Loading />;
  return (
    <div className="page-narrow stack gap-24">
      <div className="row between wrap gap-12">
        <div className="stack gap-4"><h1>Notifications</h1><span className="muted">Inbox · {data.unread} unread</span></div>
        <button className="btn btn-sm btn-secondary" disabled={!data.unread} onClick={async () => { await api("/notifications/read-all", { method: "POST" }); reload(true); }}>Mark all as read</button>
      </div>
      {data.items.length === 0 ? <div className="card empty"><h3>You're all caught up</h3><span className="muted">We'll let you know when a book or chapter is ready.</span></div> : (
        <div className="card" style={{ padding: 8 }}>
          {data.items.map((n: any) => {
            const body = <div className="row gap-12" style={{ padding: "14px 12px", alignItems: "flex-start" }}>
              <span style={{ width: 8, height: 8, borderRadius: 4, marginTop: 7, background: n.read ? "transparent" : "var(--accent)", flex: "none" }} aria-label={n.read ? undefined : "Unread"} />
              <span className="grow stack gap-4"><strong>{n.title}</strong><span className="small muted">{n.body}</span></span>
              <span className="tiny muted" style={{ whiteSpace: "nowrap" }}>{ago(n.created_at)}</span></div>;
            return n.link ? <Link key={n.id} to={n.link} style={{ color: "inherit", textDecoration: "none", display: "block", borderRadius: 10 }}>{body}</Link> : <div key={n.id}>{body}</div>;
          })}
        </div>)}
      <div className="card stack gap-12">
        <h3>Send me</h3>
        <table className="table"><thead><tr><th>Type</th><th>In app</th><th>Email</th></tr></thead>
          <tbody>{["Daily review reminder", "Book or chapter ready", "Streak at risk", "Billing and receipts", "Product updates"].map((t) => <tr key={t}><td>{t}</td><td><input type="checkbox" defaultChecked aria-label={`${t} in app`} /></td><td><input type="checkbox" disabled aria-label={`${t} email`} /></td></tr>)}</tbody></table>
        <span className="small muted">Email notifications switch on once we finish setting up our sending domain. Billing emails are required while you have a paid plan.</span>
      </div>
    </div>
  );
}
