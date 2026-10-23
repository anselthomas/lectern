import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { Spinner } from "./components";

const MAX_SECONDS = 120;
const TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus", "audio/ogg"];

export function voiceSupported() {
  return typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";
}

/** Record an answer and get it back as text (Amazon Transcribe on the server). The text is appended for editing. */
export function VoiceInput({ onText, disabled, compact }: { onText: (text: string) => void; disabled?: boolean; compact?: boolean }) {
  const [state, setState] = useState<"idle" | "recording" | "transcribing">("idle");
  const [seconds, setSeconds] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const rec = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const timer = useRef<number>();
  const stream = useRef<MediaStream | null>(null);

  useEffect(() => () => { window.clearInterval(timer.current); stream.current?.getTracks().forEach((t) => t.stop()); }, []);
  if (!voiceSupported()) return null;

  const start = async () => {
    setErr(null);
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch {
      setErr("Allow microphone access in your browser to answer by voice.");
      return;
    }
    const mimeType = TYPES.find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
    const r = new MediaRecorder(stream.current, mimeType ? { mimeType } : undefined);
    chunks.current = [];
    r.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
    r.onstop = () => upload(new Blob(chunks.current, { type: r.mimeType || mimeType || "audio/webm" }));
    rec.current = r;
    r.start(1000);
    setSeconds(0);
    setState("recording");
    timer.current = window.setInterval(() => setSeconds((s) => {
      if (s + 1 >= MAX_SECONDS) stop();
      return s + 1;
    }), 1000);
  };

  const stop = () => {
    window.clearInterval(timer.current);
    if (rec.current?.state === "recording") rec.current.stop();
    stream.current?.getTracks().forEach((t) => t.stop());
  };

  const upload = async (blob: Blob) => {
    setState("transcribing");
    try {
      const ext = blob.type.includes("mp4") ? "m4a" : blob.type.includes("ogg") ? "ogg" : "webm";
      const form = new FormData();
      form.append("audio", blob, `answer.${ext}`);
      const { text } = await api<{ text: string }>("/transcribe", { body: form });
      if (text.trim()) onText(text.trim());
      else setErr("We didn't catch any words. Try again a little closer to the mic.");
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 402)) setErr((e as Error).message);
    } finally {
      setState("idle");
    }
  };

  const mm = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  return (
    <div className="stack gap-4" style={{ alignItems: "flex-start" }}>
      {state === "idle" && (
        <button type="button" className={`btn ${compact ? "btn-sm" : "btn-sm"} btn-secondary`} disabled={disabled} onClick={start}
          aria-label="Answer by voice" title="Answer by voice">
          <span aria-hidden="true">🎤</span>{compact ? "" : " Speak instead"}
        </button>
      )}
      {state === "recording" && (
        <button type="button" className="btn btn-sm btn-danger" onClick={stop} aria-label={`Stop recording, ${mm}`}>
          <span aria-hidden="true" className="rec-dot" /> {compact ? mm : `Recording ${mm} · Stop`}
        </button>
      )}
      {state === "transcribing" && <span className="row gap-8 small muted"><Spinner />{compact ? "" : "Transcribing…"}</span>}
      {err && <span className="small field-error" role="alert">{err}</span>}
    </div>
  );
}
