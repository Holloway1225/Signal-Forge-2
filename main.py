
"""Signal Forge 2 — reference-first Suno production engine."""

import asyncio
import io
import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from lyric_architect import router as lyric_router


app = FastAPI(title="Signal Forge API", version="1.3.0")
app.include_router(lyric_router)

origins = [
    value.strip()
    for value in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:8080,http://127.0.0.1:8080"
    ).split(",")
    if value.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"]
)

MAX_AUDIO_BYTES = 12 * 1024 * 1024

SECTIONS = (
    "intro", "verse", "pre_chorus", "chorus",
    "bridge", "instrumental", "outro"
)

ANALYSIS_FIELDS = (
    "vocals", "instrumentation", "rhythm",
    "dynamics", "production", "emotion", "evidence"
)


class PromptRequest(BaseModel):
    song: str = Field(default="", max_length=200)
    artist: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=3000)
    vocals: str = Field(
        default="deep male clean vocals",
        max_length=200
    )
    intensity: int = Field(default=7, ge=1, le=10)
    atmosphere: int = Field(default=8, ge=1, le=10)
    mode: str = Field(
        default="cryptid",
        pattern="^(cryptid|neutral)$"
    )


SYSTEM = """
You are Signal Forge, a specialist in reference-informed
music production analysis and Suno prompt engineering.

Your primary goal is to translate specific musical evidence
into an actionable production blueprint for an ORIGINAL song.

EVIDENCE PRIORITY:
1. Gemini listening report from an actual recording.
2. User-supplied descriptions of the sound.
3. Last.fm metadata and genre tags.
4. Clearly labeled creative suggestions.

NEVER replace distinctive reference characteristics with
generic alternative metal or Cryptid Static defaults.

Do not claim to have listened when no listening report exists.

Never invent exact BPM, tuning, key, or section structures
as facts without evidence.

USER PREFERENCES:
Intensity, atmosphere, vocal approach and Cryptid Static
mode are adaptation preferences, not evidence about
the reference recording.

Cryptid Static mode must not automatically introduce
static, synth pads, chugging guitars, half-time breakdowns,
or guitar solos. Only use these when the listening evidence
or explicit user instructions support them.

SUNO STYLE PROMPT:
- Maximum 1000 characters.
- Aim for 600-900 characters when supported by the evidence.
- Do not pad with generic filler to meet a character target.
- Write concrete musical production language.
- Describe vocal register, phrasing and delivery.
- Describe actual drum groove and rhythmic feel.
- Describe guitar and bass textures and their placement.
- Describe electronic sounds and sound design if supported.
- Describe changes from verses into choruses.
- Describe production depth, dynamics and transitions.
- Prioritize the reference's DISTINCTIVE traits.
- Avoid artist names, lyrical themes and vague adjectives.
- Do not imitate a specific singer's identity.
- Never reproduce existing lyrics or melodies.
- No introductory phrases like "Create a track".
- Make the result immediately pasteable into Suno.

SECTION TAGS:
Return seven bracketed musical instructions:
intro, verse, pre_chorus, chorus, bridge, instrumental, outro.

Each tag should be concise but musically descriptive.
Usually 8-22 words when the evidence supports that detail.

Include combinations of:
- instrumentation
- rhythmic groove
- vocal delivery
- dynamics
- electronic textures
- transitions

Bad: [powerful release]
Bad: [dynamic shift]
Bad: [heavy riff]
Bad: [anthemic]

Better:
[Explosive syncopated guitars, tight electronic kick,
wide melodic clean vocals, layered harmonies]

Do not use identical instructions for different sections.
Do not invent a reference section that was not identified.
For missing sections, propose a fitting original-song
arrangement and label that choice in the caveat.

ANALYSIS:
The seven analysis fields MUST each be plain text strings.
Never put objects, arrays or JSON inside analysis fields.
Explain the most distinctive production observations.

EVIDENCE:
Distinguish what Gemini reported from metadata-based
inferences and user preferences.

CAVEAT:
Briefly state uncertainties and whether the recording
was actually processed.

Return ONLY a JSON object with:
{
 "analysis": {
   "vocals": "...",
   "instrumentation": "...",
   "rhythm": "...",
   "dynamics": "...",
   "production": "...",
   "emotion": "...",
   "evidence": "..."
 },
 "style_prompt": "...",
 "section_tags": {
   "intro": "[...]",
   "verse": "[...]",
   "pre_chorus": "[...]",
   "chorus": "[...]",
   "bridge": "[...]",
   "instrumental": "[...]",
   "outro": "[...]"
 },
 "caveat": "..."
}
"""


GEMINI_PROMPT = """
You are analyzing the ACTUAL AUDIO of a YouTube recording
to help design an original song with similar production
characteristics.

Analyze only what you can reasonably hear.
Do not use genre stereotypes to fill missing details.
Do not reproduce lyrics or melodies.

First identify whether the recording appears to be:
- official studio recording
- live performance
- cover or remix
- commentary or unrelated video
- uncertain

Describe the audible music in detail.

1. VOCALS
Register, clean or harsh delivery, sung versus spoken
phrasing, rhythmic articulation, harmonies, processing,
and changes between sections.

2. DRUMS AND GROOVE
Electronic versus acoustic percussion, kick and snare,
hi-hats, programmed patterns, 808 or sub-bass if audible,
syncopation, groove and rhythmic contrast.

3. GUITARS AND BASS
Distortion, guitar tone, riff patterns, clean layers,
palm muting, low-end movement and how the instruments
interact with electronic elements.

4. ELECTRONIC PRODUCTION
Synths, glitches, sampled textures, effects, ambience,
drops, transitions and sound design.

5. ARRANGEMENT
Identify intro, verses, pre-choruses, choruses, bridge,
instrumental and outro ONLY when distinguishable.
Describe what each section sounds like.
Mention timestamps only when confident.

6. DYNAMICS AND MIX
How the recording moves between restrained and heavy
passages, changes in density, vocal prominence, reverb,
delay, stereo width and overall production.

7. SIGNATURE SOUND
Identify 5-8 distinctive audible traits that separate
this recording from a generic genre description.

8. UNCERTAINTY
Identify anything you could not reliably hear.

Do not claim specific BPM, key, tuning, instrument
models or technical processing without evidence.

Do not say merely "heavy guitars", "powerful chorus",
"dynamic shift", or "atmospheric textures".
Explain what is actually producing those effects.

If the audio cannot be accessed or meaningfully analyzed,
say that explicitly instead of guessing.
"""


def _lastfm_get(params: dict) -> dict:
    query = urlencode({
        **params,
        "api_key": os.environ["LASTFM_API_KEY"],
        "format": "json",
        "autocorrect": "1"
    })

    req = Request(
        "https://ws.audioscrobbler.com/2.0/?" + query,
        headers={"User-Agent": "SignalForge/1.3"}
    )

    with urlopen(req, timeout=9) as response:
        return json.load(response)


def _tags(value: Any) -> list[str]:
    if isinstance(value, dict):
        value = value.get("tag", [])

    if isinstance(value, dict):
        value = [value]

    if not isinstance(value, list):
        return []

    return [
        str(item["name"])[:80]
        for item in value
        if isinstance(item, dict) and item.get("name")
    ][:12]


def lookup_lastfm(song: str, artist: str) -> dict:
    if not os.getenv("LASTFM_API_KEY"):
        return {"status": "not_configured"}

    if not song or not artist:
        return {"status": "not_queried"}

    try:
        result = _lastfm_get({
            "method": "track.getInfo",
            "track": song,
            "artist": artist
        })

        track = result.get("track")

        if not isinstance(track, dict):
            return {"status": "not_found"}

        artist_data = track.get("artist", {})
        artist_name = (
            artist_data.get("name", artist)
            if isinstance(artist_data, dict)
            else str(artist_data)
        )

        metadata = {
            "status": "found",
            "track": track.get("name", song),
            "artist": artist_name,
            "track_tags": _tags(track.get("toptags")),
            "source": "Last.fm"
        }

        if not metadata["track_tags"]:
            try:
                artist_info = _lastfm_get({
                    "method": "artist.getTopTags",
                    "artist": artist_name
                })
                metadata["artist_tags"] = _tags(
                    artist_info.get("toptags")
                )
            except Exception:
                metadata["artist_tags"] = []

        return metadata

    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return {"status": "unavailable"}


def youtube_url(value: str) -> str | None:
    parsed = urlparse(value.strip())

    if parsed.scheme not in ("https", "http"):
        return None

    host = (parsed.hostname or "").lower()
    video_id = None

    if host in (
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com"
    ):
        if parsed.path == "/watch":
            video_id = parse_qs(
                parsed.query
            ).get("v", [None])[0]
        elif parsed.path.startswith(
            ("/shorts/", "/live/", "/embed/")
        ):
            parts = parsed.path.split("/")
            if len(parts) > 2:
                video_id = parts[2]

    elif host in ("youtu.be", "www.youtu.be"):
        video_id = parsed.path.strip("/").split("/")[0]

    if not video_id or not re.fullmatch(
        r"[A-Za-z0-9_-]{11}", video_id
    ):
        return None

    return "https://www.youtube.com/watch?v=" + video_id


def gemini_listen(url: str) -> dict:
    key = os.getenv("GEMINI_API_KEY")

    if not key:
        return {
            "status": "failed",
            "error": "GEMINI_API_KEY is missing in Render"
        }

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    endpoint = (
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models/{model}:generateContent"
    )

    body = {
        "contents": [{
            "parts": [
                {"file_data": {"file_uri": url}},
                {"text": GEMINI_PROMPT}
            ]
        }],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 3500
        }
    }

    req = Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": key
        },
        method="POST"
    )

    try:
        with urlopen(req, timeout=110) as response:
            data = json.load(response)

        report = "\n".join(
            part.get("text", "")
            for candidate in data.get("candidates", [])
            for part in candidate.get(
                "content", {}
            ).get("parts", [])
            if isinstance(part, dict)
        ).strip()

        if len(report) < 150:
            return {
                "status": "failed",
                "error": "Gemini returned insufficient analysis"
            }

        return {
            "status": "analyzed",
            "model": model,
            "url": url,
            "report": report[:18000]
        }

    except HTTPError as exc:
        return {
            "status": "failed",
            "error": (
                f"Gemini HTTP {exc.code}. "
                "Check quota, model access, and video availability."
            )
        }

    except (URLError, TimeoutError, ValueError, OSError) as exc:
        return {
            "status": "failed",
            "error": f"Gemini request failed: {type(exc).__name__}"
        }


def flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()

    if isinstance(value, dict):
        return "; ".join(
            f"{key.replace('_', ' ')}: {flatten_text(item)}"
            for key, item in value.items()
            if item is not None
        )

    if isinstance(value, list):
        return "; ".join(flatten_text(item) for item in value)

    if value is None:
        return ""

    return str(value)


def clean_result(data: dict) -> dict:
    analysis = data.get("analysis")

    if not isinstance(analysis, dict):
        analysis = {}

    data["analysis"] = {
        key: flatten_text(analysis.get(key, ""))
        for key in ANALYSIS_FIELDS
    }

    tags = data.get("section_tags")

    if not isinstance(tags, dict):
        tags = {}

    cleaned_tags = {}

    for section in SECTIONS:
        value = flatten_text(tags.get(section, ""))

        if not value:
            value = "Production direction not established"

        if not value.startswith("["):
            value = "[" + value

        if not value.endswith("]"):
            value += "]"

        cleaned_tags[section] = value

    data["section_tags"] = cleaned_tags
    data["caveat"] = flatten_text(data.get("caveat", ""))
    data["style_prompt"] = flatten_text(
        data.get("style_prompt", "")
    )

    return data


async def generate(payload: dict) -> dict:
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            503,
            "OPENAI_API_KEY is missing in Render"
        )

    client = AsyncOpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        timeout=60.0
    )

    try:
        result = await client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0.3,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps(payload)
                }
            ]
        )

        data = json.loads(
            result.choices[0].message.content or "{}"
        )

        if not isinstance(data, dict):
            raise ValueError("Invalid AI output")

        data = clean_result(data)

        if not data["style_prompt"]:
            raise ValueError("Missing style prompt")

        if len(data["style_prompt"]) > 1000:
            shorter = await client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Return JSON with one key: style_prompt. "
                            "Rewrite the supplied Suno style prompt "
                            "to at most 1000 characters. Preserve "
                            "the most distinctive evidenced sounds."
                        )
                    },
                    {
                        "role": "user",
                        "content": data["style_prompt"]
                    }
                ]
            )

            compressed = json.loads(
                shorter.choices[0].message.content or "{}"
            ).get("style_prompt", "")

            if not isinstance(compressed, str):
                raise ValueError("Invalid compressed prompt")

            if len(compressed) > 1000:
                raise ValueError("Prompt remains over 1000 characters")

            data["style_prompt"] = compressed

        return data

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            502,
            f"AI generation failed: {type(exc).__name__}"
        ) from exc


@app.get("/health")
def health():
    return {
        "ok": True,
        "version": "1.3.0",
        "lastfm_configured": bool(
            os.getenv("LASTFM_API_KEY")
        ),
        "gemini_configured": bool(
            os.getenv("GEMINI_API_KEY")
        )
    }


@app.post("/api/generate")
async def create_prompt(request: PromptRequest):
    if not (
        request.song.strip()
        or request.notes.strip()
    ):
        raise HTTPException(
            422,
            "Enter a reference song or sound description"
        )

    link = youtube_url(request.song)

    if not link:
        for word in request.notes.split():
            link = youtube_url(word)
            if link:
                break

    if link:
        listened = await asyncio.to_thread(
            gemini_listen, link
        )

        if listened["status"] != "analyzed":
            raise HTTPException(
                422,
                "YouTube listening failed: "
                + listened.get("error", "Unknown error")
            )

        metadata = await asyncio.to_thread(
            lookup_lastfm,
            "" if youtube_url(request.song)
            else request.song.strip(),
            request.artist.strip()
        )

        data = await generate({
            "input_type": "Gemini YouTube audio analysis",
            **request.model_dump(),
            "gemini_audio_analysis": listened["report"],
            "lastfm": metadata,
            "instruction": (
                "Base the Suno style prompt and each section "
                "tag on the Gemini listening report. "
                "Preserve its distinctive musical features. "
                "Use detailed concrete descriptions, not "
                "generic genre labels or preset arrangements."
            )
        })

        data["reference_lookup"] = metadata
        data["audio_analysis"] = {
            "status": "analyzed",
            "source": "Gemini YouTube audio/video input",
            "model": listened["model"],
            "youtube_url": link
        }

        data["caveat"] = (
            data["caveat"]
            + " Gemini processed the public YouTube reference; "
            "descriptions are AI listening interpretations."
        ).strip()

        return data

    metadata = await asyncio.to_thread(
        lookup_lastfm,
        request.song.strip(),
        request.artist.strip()
    )

    data = await generate({
        "input_type": "metadata only; no recording listened to",
        **request.model_dump(),
        "lastfm": metadata,
        "instruction": (
            "Be explicit about the absence of audio analysis. "
            "Do not present inferred instruments, sections "
            "or production details as verified facts."
        )
    })

    data["reference_lookup"] = metadata

    data["caveat"] = (
        data["caveat"]
        + " No recording was listened to; musical details "
        "beyond supplied information are suggestions."
    ).strip()

    return data


@app.post("/api/analyze-audio")
async def analyze_audio(
    audio: UploadFile = File(...),
    notes: str = Form(""),
    vocals: str = Form("deep male clean vocals"),
    intensity: int = Form(7),
    atmosphere: int = Form(8),
    mode: str = Form("cryptid")
):
    if (
        not 1 <= intensity <= 10
        or not 1 <= atmosphere <= 10
        or mode not in ("cryptid", "neutral")
    ):
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

        y, sr = librosa.load(
            io.BytesIO(raw),
            sr=22050,
            mono=True,
            duration=90
        )

        if len(y) < sr:
            raise ValueError("Audio too short")

        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        rms = librosa.feature.rms(y=y)[0]
        centroid = librosa.feature.spectral_centroid(
            y=y, sr=sr
        )[0]
        zcr = librosa.feature.zero_crossing_rate(y)[0]

        features = {
            "analyzed_seconds": round(len(y) / sr, 1),
            "estimated_tempo_bpm": round(
                float(np.asarray(tempo).reshape(-1)[0]), 1
            ),
            "average_rms": round(float(np.mean(rms)), 4),
            "dynamic_rms_p10_p90": [
                round(float(v), 4)
                for v in np.percentile(rms, [10, 90])
            ],
            "spectral_centroid_hz": round(
                float(np.mean(centroid))
            ),
            "zero_crossing_rate": round(
                float(np.mean(zcr)), 4
            )
        }

    except Exception as exc:
        raise HTTPException(
            422,
            "Could not decode audio. Try a WAV file."
        ) from exc

    return await generate({
        "input_type": (
            "audio feature measurements, "
            "not full perceptual listening"
        ),
        "features": features,
        "notes": notes,
        "vocals": vocals,
        "intensity": intensity,
        "atmosphere": atmosphere,
        "mode": mode,
        "instruction": (
            "Do not infer exact instruments, vocal identity, "
            "genre or tuning from numerical features alone."
        )
    })
