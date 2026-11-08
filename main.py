"""AI Suno prompt generator. Deploy behind a rate-limited proxy for public use."""
import io
import json
import os
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

app = FastAPI(title="Suno Prompt Machine API", version="1.0.0")
origins = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
MAX_AUDIO_BYTES = 12 * 1024 * 1024

class PromptRequest(BaseModel):
    song: str = Field(default="", max_length=200)
    artist: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=3000)
    vocals: str = Field(default="deep male clean vocals", max_length=200)
    intensity: int = Field(default=7, ge=1, le=10)
    atmosphere: int = Field(default=8, ge=1, le=10)
    mode: str = Field(default="cryptid", pattern="^(cryptid|neutral)$")

SYSTEM = """You are a meticulous music-production analyst and Suno prompt designer. Return ONLY a JSON object with keys: analysis (object with keys vocals, instrumentation, rhythm, dynamics, production, emotion, evidence), style_prompt (string, maximum 1000 characters), section_tags (object with keys intro, verse, pre_chorus, chorus, bridge, instrumental, outro), and caveat (string). Never quote or recreate existing lyrics or melodies. Do not assert you listened to a reference when only title/artist were supplied; say any title-based analysis is inferential and may be inaccurate. Use audio-derived metrics only when provided. Prefer concrete audible/production instructions over artist names. No imitation of a specific singer's identity. Do not make up BPM, key, or tuning. Cryptid Static mode: dark melodic alternative metal, emotional clean vocals, restrained verses, cinematic static textures, crushing choruses, tasteful melodic guitar leads, no screaming unless requested. Ensure style_prompt is immediately pasteable into Suno and <=1000 characters. Every section tag is a concise bracketed production direction, not lyrics. Avoid explanations inside style_prompt."""

async def generate(payload: dict):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(503, "OPENAI_API_KEY is not configured on the backend")
    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=45.0)
    try:
        result = await client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0.5,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(payload)}],
        )
        data = json.loads(result.choices[0].message.content or "{}")
        if not isinstance(data.get("style_prompt"), str) or not isinstance(data.get("section_tags"), dict):
            raise ValueError("Incomplete model output")
        if len(data["style_prompt"]) > 1000:
            # Ask the model to shorten instead of silently chopping musical instructions.
            shortened = await client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role": "system", "content": "Return JSON with exactly one key style_prompt. Compress the supplied Suno style prompt to <= 1000 characters while preserving the production detail."}, {"role": "user", "content": data["style_prompt"]}],
                response_format={"type": "json_object"},
            )
            data["style_prompt"] = json.loads(shortened.choices[0].message.content or "{}")["style_prompt"][:1000]
        return data
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"AI generation failed: {type(exc).__name__}") from exc

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/api/generate")
async def create_prompt(request: PromptRequest):
    if not (request.song.strip() or request.notes.strip()):
        raise HTTPException(422, "Enter a reference song or a sound description")
    return await generate({"input_type": "reference metadata / description (NOT listened to)", **request.model_dump()})

@app.post("/api/analyze-audio")
async def analyze_audio(
    audio: UploadFile = File(...),
    notes: str = Form(""),
    vocals: str = Form("deep male clean vocals"),
    intensity: int = Form(7),
    atmosphere: int = Form(8),
    mode: str = Form("cryptid"),
):
    if not 1 <= intensity <= 10 or not 1 <= atmosphere <= 10 or mode not in ("cryptid", "neutral"):
        raise HTTPException(422, "Invalid settings")
    if len(notes) > 3000 or len(vocals) > 200:
        raise HTTPException(422, "Text too long")
    # Strict read cap; avoid loading arbitrary-sized files into memory.
    raw = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio exceeds 12 MB")
    if not raw:
        raise HTTPException(422, "Empty audio")
    try:
        import librosa
        import numpy as np
        y, sr = librosa.load(io.BytesIO(raw), sr=22050, mono=True, duration=90)
        if len(y) < sr:
            raise ValueError("Audio too short")
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        rms = librosa.feature.rms(y=y)[0]
        centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
        zcr = librosa.feature.zero_crossing_rate(y)[0]
        features = {
            "analyzed_seconds": round(len(y) / sr, 1),
            "estimated_tempo_bpm": round(float(np.asarray(tempo).reshape(-1)[0]), 1),
            "average_rms": round(float(np.mean(rms)), 4),
            "dynamic_rms_p10_p90": [round(float(v), 4) for v in np.percentile(rms, [10, 90])],
            "spectral_centroid_hz": round(float(np.mean(centroid))),
            "zero_crossing_rate": round(float(np.mean(zcr)), 4),
        }
    except Exception as exc:
        raise HTTPException(422, "Could not decode audio. Try a WAV file, or install FFmpeg for MP3 support.") from exc
    return await generate({"input_type": "audio feature measurements, NOT full perceptual listening", "features": features, "notes": notes, "vocals": vocals, "intensity": intensity, "atmosphere": atmosphere, "mode": mode, "instruction": "Be explicit that the metrics do not establish vocal gender, instrumentation, guitar tuning, or exact genre. Treat these as user preferences or inferences, not measured facts."})
