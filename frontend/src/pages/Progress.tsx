import { useState } from "react";
import { Link } from "react-router-dom";
import { ErrorBox, formatMinutes, Loading } from "../components";
import { useApi } from "../state";

const periods = [[14, "Last 14 days"], [30, "Last 30 days"], [100000, "All time"]] as const;

export default function Progress() {
  const [days, setDays] = useState<number>(14);
  const { data, error, reload } = useApi<any>(`/progress?days=${days}`, [days]);
  if (error) return <div className="page"><ErrorBox error={error} retry={() => reload()} /></div>;
  if (!data) return <Loading />;
  const max = Math.max(data.goal_minutes * 1.5, ...data.series.map((d: any) => d.minutes), 1);
  const h = Math.floor(data.minutes_total / 60), m = data.minutes_total % 60;
  return (
    <div className="page stack gap-24">
      <div className="row between wrap gap-12">
        <h1>Progress</h1>
        <div className="seg" role="radiogroup" aria-label="Period">{periods.map(([v, l]) => <button key={v} role="radio" aria-checked={days === v} onClick={() => setDays(v)}>{l}</button>)}</div>
      </div>
      <div className="row gap-16 wrap">
        {[["Time studied", h ? `${h} h ${m} m` : `${m} min`], ["Day streak", `${data.streak} day${data.streak === 1 ? "" : "s"}`], ["Cards reviewed", data.cards_reviewed], ["Average quiz score", data.quiz_avg != null ? `${data.quiz_avg}%` : "—"]].map(([l, v]) => (
          <div key={l as string} className="card-sm grow stack gap-8" style={{ flexBasis: 200 }}><span className="label">{l}</span><strong style={{ fontSize: 26 }}>{v}</strong></div>))}
      </div>
      {data.series.length > 0 && (
        <div className="card stack gap-12">
          <div className="row between"><h3>Minutes studied per day</h3><span className="small muted">Goal: {formatMinutes(data.goal_minutes)} a day</span></div>
          <div className="chart" role="img" aria-label="Minutes studied per day">
            <div style={{ position: "absolute", left: 0, right: 0, bottom: `${(data.goal_minutes / max) * 100}%`, borderTop: "1px dashed var(--line-3)" }} />
            {data.series.map((d: any) => (
              <div key={d.day} className="col" title={`${d.day}: ${d.minutes} min`}>
                <span className={`b${d.minutes >= data.goal_minutes ? " met" : ""}`} style={{ height: `${(d.minutes / max) * 100}%` }} />
              </div>))}
          </div>
          <div className="row between tiny muted"><span>{data.series[0].day}</span><span>{data.series[data.series.length - 1].day}</span></div>
        </div>
      )}
      <div className="card stack gap-12">
        <h3>By book</h3>
        {data.by_book.length === 0 ? <span className="muted">No books yet.</span> : (
          <div style={{ overflowX: "auto" }}><table className="table"><thead><tr><th>Book</th><th>Chapters mastered</th><th>Quiz avg</th><th>Time</th></tr></thead>
            <tbody>{data.by_book.map((b: any) => <tr key={b.id}><td><Link to={`/books/${b.id}`}>{b.title}</Link></td><td>{b.chapters_mastered} / {b.chapters_total}</td><td>{b.quiz_avg != null ? `${b.quiz_avg}%` : "—"}</td><td>{b.minutes >= 60 ? `${Math.floor(b.minutes / 60)} h ${b.minutes % 60} m` : `${b.minutes} m`}</td></tr>)}</tbody></table></div>)}
      </div>
      <div className="card stack gap-12">
        <h3>Needs attention</h3>
        {data.attention.length === 0 ? <span className="muted">Nothing flagged. Missed quiz questions and cards you forget show up here.</span> :
          data.attention.map((a: any) => (
            <div key={a.chapter_id} className="row between gap-12" style={{ padding: "8px 0", borderBottom: "1px solid var(--bg-3)" }}>
              <span className="stack gap-4"><strong>{a.title}</strong><span className="small muted">{a.book} · Ch. {a.chapter_n}</span></span>
              <Link to={`/review?book=${a.book_id}`}>{a.cards} card{a.cards === 1 ? "" : "s"} →</Link>
            </div>))}
      </div>
    </div>
  );
}
