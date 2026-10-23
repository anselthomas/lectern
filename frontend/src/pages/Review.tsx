import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorBox, Loading, PageChip, SourceViewer, Spinner } from "../components";
import { useApi } from "../state";

const ratings = [[1, "Again"], [2, "Hard"], [3, "Good"], [4, "Easy"]] as const;

export default function Review() {
  const [params] = useSearchParams();
  const book = params.get("book");
  const { data, error, loading, reload } = useApi<any>(`/review/due${book ? `?book_id=${book}` : ""}`);
  const [i, setI] = useState(0);
  const [shown, setShown] = useState(false);
  const [busy, setBusy] = useState(false);
  const [viewer, setViewer] = useState<{ book: string; page: number } | null>(null);
  const cards = data?.cards ?? [];
  const card = cards[i];
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (!card || busy || (e.target as HTMLElement)?.tagName === "INPUT") return;
      if (e.key === " " && !shown) { e.preventDefault(); setShown(true); }
      if (shown && ["1", "2", "3", "4"].includes(e.key)) rate(+e.key);
    };
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  });
  if (error) return <div className="page-narrow"><ErrorBox error={error} retry={() => reload()} /></div>;
  if (loading && !data) return <Loading label="Gathering today's cards…" />;
  const rate = async (r: number) => {
    setBusy(true);
    try { await api(`/review/${card.id}`, { body: { rating: r } }); setShown(false); setI(i + 1); } finally { setBusy(false); }
  };
  if (!card) return (
    <div className="page-narrow">
      <div className="card empty">
        <h2>{cards.length ? "Review done for today" : data?.total_cards ? "Nothing due right now" : "No flashcards yet"}</h2>
        <p className="muted" style={{ maxWidth: 420 }}>{data?.total_cards ? "Next cards come back when you're about to forget them. Keep going on your current chapter while it's fresh." : "Finish a section or a chapter quiz — key terms and missed questions become cards automatically."}</p>
        <div className="row gap-12"><Link className="btn btn-strong" to="/library">Continue studying</Link>{cards.length > 0 && <button className="btn btn-secondary" onClick={() => { setI(0); reload(); }}>Review again</button>}</div>
      </div>
    </div>
  );
  return (
    <div className="page-narrow stack gap-24">
      <div className="row between"><span className="small muted">Daily review · {book ? "this book" : "all books"}</span><span className="mono muted">{i + 1} / {cards.length}</span></div>
      <div className="steps">{cards.map((c: any, k: number) => <span key={c.id} className={k < i ? "done" : k === i ? "cur" : ""} />)}</div>
      <div className="card flash">
        <div className="row gap-8 wrap center"><span className="small muted">{card.book.title}</span>{card.tag && <span className="badge badge-muted">{card.tag}</span>}{card.source === "missed_question" && <span className="badge badge-warn">Missed in quiz</span>}</div>
        <p style={{ fontSize: 22, fontWeight: 800, lineHeight: 1.35, maxWidth: 560 }}>{card.front}</p>
        {shown && <>
          <hr className="divider" style={{ width: "60%" }} />
          <div className="reading" style={{ fontSize: 17, maxWidth: 560, whiteSpace: "pre-wrap" }}>{card.back}</div>
          <PageChip page={card.page} label={card.page_label} onOpen={(p) => setViewer({ book: card.book.id, page: p })} />
        </>}
      </div>
      {!shown ? <button className="btn btn-strong" style={{ alignSelf: "center", minWidth: 220 }} onClick={() => setShown(true)}>Show answer <span className="mono" style={{ opacity: .6 }}>space</span></button> : (
        <div className="row gap-8 center wrap">
          {ratings.map(([r, l]) => (
            <button key={r} className={`btn ${r === 3 ? "btn-primary" : "btn-secondary"}`} style={{ flexDirection: "column", height: 64, minWidth: 110, gap: 2 }} disabled={busy} onClick={() => rate(r)} aria-label={`${l}, next review in ${card.intervals?.[r] ?? "later"}`}>
              <span>{l}</span><span className="tiny" style={{ opacity: .75, fontWeight: 600 }}>{card.intervals?.[r]}</span>
            </button>))}
          {busy && <Spinner />}
        </div>)}
      <span className="small muted" style={{ textAlign: "center" }}>Next review dates are set by the FSRS scheduler.</span>
      {viewer && <SourceViewer bookId={viewer.book} page={viewer.page} onClose={() => setViewer(null)} />}
    </div>
  );
}
