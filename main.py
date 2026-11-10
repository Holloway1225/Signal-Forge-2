"""Signal Forge backend: Last.fm-enriched reference prompts and audio metrics."""
import asyncio
import io
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from lyric_architect import router as lyric_router

app = FastAPI(title="Signal Forge API", version="1.1.0")
app.include_router(lyric_router)
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

SYSTEM = """You are Signal Forge, a careful music-production researcher and Suno prompt designer.
Return ONLY JSON with keys:
analysis: object with vocals, instrumentation, rhythm, dynamics, production, emotion, evidence;
style_prompt: string at most 1000 characters;
section_tags: object with intro, verse, pre_chorus, chorus, bridge, instrumental, outro;
caveat: string.

PRIORITY: Reproduce the musical production CHARACTERISTICS of the user's reference, NOT a generic house sound. Reference evidence outranks the user's mode and preset preferences. If genre tags suggest electronic, pop, R&B, hip-hop, industrial, or other elements, do not replace them with generic alternative metal. Describe contrasting section textures and transitions when supported. Do not inject static, atmospheric synths, crushing guitars, guitar solos, or any other Cryptid Static cliché unless evidence or user notes support it. Cryptid mode is a light preference for emotionally expressive clean vocals and no screaming, not a genre override. User-supplied notes may provide additional specifics; distinguish them from independently verified data.

Last.fm tags and metadata are descriptive metadata, NOT a recording analysis. They may be broad, user-generated, or missing. Never claim to have heard or measured the recording for metadata-only input. Do not invent exact guitar tuning, instruments, vocal techniques, beats, BPM, production details, song structure, or transitions as verified facts. Where reliable detail is missing, be explicit that the proposed arrangement is a creative interpretation rather than a faithful sonic transcription. Do not invent reference-specific section features from genre tags alone. Do not cite Last.fm as evidence for details it does not supply.

Make style_prompt a compact, immediately usable Suno production prompt, with the strongest supported sonic traits first. Avoid artist names and any imitation of a particular singer's identity. Never recreate copyrighted lyrics or melodies. Each section tag must be a short bracketed musical direction, not prose paragraphs or lyrics. The section tags can be creative adaptations, but must not pretend to document the original recording. Never fabricate precision (key, BPM, tuning) not present in the input. If the reference is not found, clearly disclose that and do not make up its genre.
"""


def _lastfm_get(params: dict[str, str]) -> dict[str, Any]:
    query = urlencode({**params, "api_key": os.environ["LASTFM_API_KEY"], "format": "json", "autocorrect": "1"})
    req = Request("https://ws.audioscrobbler.com/2.0/?" + query, headers={"User-Agent": "SignalForge/1.1 (music-reference metadata)"})
    with urlopen(req, timeout=9) as response:
        return json.load(response)


def _tag_names(raw: Any, limit: int = 12) -> list[str]:
    if isinstance(raw, dict):
        raw = raw.get("tag", [])
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(item["name"])[:80] for item in raw if isinstance(item, dict) and item.get("name")][:limit]


def _lookup_lastfm(song: str, artist: str) -> dict[str, Any]:
    if not os.getenv("LASTFM_API_KEY"):
        return {"status": "not_configured", "message": "LASTFM_API_KEY not configured"}
    if not song or not artist:
        return {"status": "not_queried", "message": "Both song title and artist are needed for a reliable track lookup"}
    try:
        track = _lastfm_get({"method": "track.getInfo", "track": song, "artist": artist})
        if "error" in track or not isinstance(track.get("track"), dict):
            return {"status": "not_found", "message": "Last.fm did not identify this track"}
        item = track["track"]
        track_artist = item.get("artist", {})
        if isinstance(track_artist, dict):
            track_artist = track_artist.get("name", artist)
        result: dict[str, Any] = {
            "status": "found",
            "track": str(item.get("name", song))[:200],
            "artist": str(track_artist)[:200],
            "track_tags": _tag_names(item.get("toptags")),
            "album": str((item.get("album") or {}).get("title", ""))[:200] if isinstance(item.get("album"), dict) else "",
            "duration_ms": item.get("duration"),
            "source": "Last.fm track.getInfo",
        }
        # Track tags can be empty even when artist tags are available.
        if not result["track_tags"]:
            try:
                artist_info = _lastfm_get({"method": "artist.getTopTags", "artist": str(track_artist)})
                result["artist_tags"] = _tag_names(artist_info.get("toptags"))
            except (HTTPError, URLError, TimeoutError, ValueError, OSError):
                result["artist_tags"] = []
        return result
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        return {"status": "unavailable", "message": f"Last.fm lookup unavailable ({type(exc).__name__})"}


async def generate(payload: dict):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(503, "OPENAI_API_KEY is not configured on the backend")
    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=45.0)
    try:
        result = await client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0.35,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(payload)}],
        )
        data = json.loads(result.choices[0].message.content or "{}")
        if not isinstance(data.get("style_prompt"), str) or not isinstance(data.get("section_tags"), dict):
            raise ValueError("Incomplete model output")
        if len(data["style_prompt"]) > 1000:
            shortened = await client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role": "system", "content": "Return JSON with exactly one key style_prompt. Compress to at most 1000 characters, retaining only evidence-supported production detail."}, {"role": "user", "content": data["style_prompt"]}],
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
    return {"ok": True, "lastfm_configured": bool(os.getenv("LASTFM_API_KEY"))}


@app.post("/api/generate")
async def create_prompt(request: PromptRequest):
    if not (request.song.strip() or request.notes.strip()):
        raise HTTPException(422, "Enter a reference song or a sound description")
    lastfm = await asyncio.to_thread(_lookup_lastfm, request.song.strip(), request.artist.strip())
    data = await generate({
        "input_type": "track metadata and/or user description; NO audio listening",
        **request.model_dump(),
        "lastfm": lastfm,
        "instruction": "Prioritize reference evidence. Last.fm tags are user-generated descriptions, not evidence of specific audible instruments or song sections. Avoid the default Cryptid Static arrangement unless the reference or user explicitly supports it.",
    })
    data["reference_lookup"] = lastfm
    caveat = str(data.get("caveat") or "").strip()
    disclosure = "No recording was listened to; production details beyond supplied metadata/notes are suggestions, not verified analysis."
    if lastfm.get("status") != "found":
        disclosure = f"Last.fm lookup: {lastfm.get('status', 'unknown')}. " + disclosure
    data["caveat"] = f"{caveat} {disclosure}".strip()
    return data


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
    return await generate({
        "input_type": "audio feature measurements, NOT full perceptual listening",
        "features": features, "notes": notes, "vocals": vocals,
        "intensity": intensity, "atmosphere": atmosphere, "mode": mode,
        "instruction": "Metrics do not establish vocal gender, instrumentation, guitar tuning, or exact genre. Treat those as user preferences or inferences, not measured facts.",
    })
