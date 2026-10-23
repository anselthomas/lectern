"""Voice answers: a short recording is transcribed with Amazon Transcribe and returned as text for the learner to edit.

Audio and transcript files live under tmp/voice/ in the uploads bucket only for the length of the request
(the bucket also expires tmp/ after a day as a backstop).
"""
import json
import os
import time
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..auth import current_user
from ..aws import s3, transcribe
from ..config import settings
from ..db import get_db
from ..limits import check_voice
from ..models import User
from .. import telemetry

router = APIRouter(prefix="/api")
MAX_BYTES = 10 * 1024 * 1024
FORMATS = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4", "audio/x-m4a": "mp4", "audio/m4a": "mp4",
           "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/flac": "flac"}
WAIT_SECONDS = 50  # stays under CloudFront's 60 s origin timeout


@router.post("/transcribe")
def transcribe_audio(audio: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = check_voice(db, user)
    ctype = (audio.content_type or "").split(";")[0].strip().lower()
    fmt = FORMATS.get(ctype) or os.path.splitext(audio.filename or "")[1].lstrip(".").lower().replace("m4a", "mp4")
    if fmt not in set(FORMATS.values()):
        raise HTTPException(400, {"code": "bad_audio", "message": "That audio format isn't supported. Try again in Chrome, Edge or Safari."})
    data = audio.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, {"code": "audio_too_long", "message": "Recordings can be up to about 2 minutes."})
    if len(data) < 2000:
        raise HTTPException(400, {"code": "audio_too_short", "message": "We didn't catch anything. Hold the button a little longer."})

    job = f"lectern-{uuid.uuid4().hex}"
    media_key = f"tmp/voice/{user.id}/{job}.{fmt}"
    out_key = f"tmp/voice/{user.id}/{job}.json"
    bucket = settings.uploads_bucket
    s3().put_object(Bucket=bucket, Key=media_key, Body=data, ContentType=ctype or "application/octet-stream")
    try:
        transcribe().start_transcription_job(
            TranscriptionJobName=job, Media={"MediaFileUri": f"s3://{bucket}/{media_key}"}, MediaFormat=fmt,
            IdentifyLanguage=True, LanguageOptions=["en-IN", "en-US", "en-GB"],
            OutputBucketName=bucket, OutputKey=out_key)
        deadline = time.time() + WAIT_SECONDS
        status, info = "IN_PROGRESS", {}
        while time.time() < deadline:
            info = transcribe().get_transcription_job(TranscriptionJobName=job)["TranscriptionJob"]
            status = info["TranscriptionJobStatus"]
            if status in ("COMPLETED", "FAILED"):
                break
            time.sleep(1)
        if status != "COMPLETED":
            reason = info.get("FailureReason", "took too long")
            raise HTTPException(502, {"code": "transcription_failed", "message": f"We couldn't transcribe that ({reason}). Try again or type instead."})
        result = json.loads(s3().get_object(Bucket=bucket, Key=out_key)["Body"].read())
        text = " ".join(t["transcript"] for t in result["results"]["transcripts"]).strip()
        seconds = max((float(i.get("end_time", 0)) for i in result["results"].get("items", [])), default=0.0)
        with telemetry.scope(user_id=user.id, feature="voice"):
            telemetry.record_call(kind="transcribe", model="amazon-transcribe", units=round(seconds, 1),
                                  cost=telemetry.transcribe_cost(seconds))
            telemetry.event("voice_clip", seconds=round(seconds, 1), language=info.get("LanguageCode"), words=len(text.split()))
        row.voice_clips += 1
        db.commit()
        return {"text": text, "language": info.get("LanguageCode")}
    finally:
        for key in (media_key, out_key):
            try:
                s3().delete_object(Bucket=bucket, Key=key)
            except Exception:
                pass
        try:
            transcribe().delete_transcription_job(TranscriptionJobName=job)
        except Exception:
            pass
