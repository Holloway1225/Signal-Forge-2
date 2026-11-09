
import json
import os
import re

from fastapi import APIRouter, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

router = APIRouter()

SECTION = re.compile(r"^\s*\[([^\]\n]+)\]\s*$")


class LyricRequest(BaseModel):
    lyrics: str = Field(min_length=1, max_length=5000)
    sound: str = Field(min_length=1, max_length=1500)
    preserve_lyrics: bool = True
    add_instrumentals: bool = True


def split_sections(lyrics):
    sections = []
    current = None

    for line in lyrics.splitlines():
        match = SECTION.fullmatch(line)

        if match:
            current = {
                "heading": match.group(1),
                "lines": []
            }
            sections.append(current)

        elif current is None:
            current = {
                "heading": "Intro",
                "lines": []
            }
            sections.append(current)
            current["lines"].append(line)

        else:
            current["lines"].append(line)

    return sections


SYSTEM = """
You are an expert music-production arranger specializing
in detailed Suno section instructions.

Your task is to design a production arrangement based
on the supplied musical reference blueprint.

You must NOT generate or rewrite song lyrics.

Return only a JSON object with a key named "sections".

"sections" must be an array containing exactly one
object per supplied song section, in the same order.

Each object must contain:
- "direction": a detailed production instruction
- "instrumental_after": an optional instrumental-only
  production instruction, or an empty string

Production directions must be specific and musical.

Consider:
- vocal technique and delivery
- instrumentation and instrument entrances
- rhythmic feel and drum patterns
- bass and guitar textures
- dynamics and intensity
- atmosphere and electronic layers
- transitions and arrangement development
- stereo width and production character

Use the supplied reference blueprint to guide every
section. Do not invent unsupported details as facts
about the reference recording.

Different sections should evolve musically.
Do not repeat generic instructions throughout.

Keep each direction concise enough for Suno.
Never include lyric words in directions.
Never imitate an identifiable singer's voice.
Never reproduce a reference melody.

When instrumentals are disabled, return an empty
instrumental_after for every section.

Only suggest instrumental passages at musically
appropriate points, not after every section.
"""


@router.post("/api/tag-lyrics")
async def tag_lyrics(req: LyricRequest):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            503,
            "OPENAI_API_KEY is not configured"
        )

    sections = split_sections(req.lyrics)

    if not sections:
        raise HTTPException(422, "No lyrics found")

    client = AsyncOpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        timeout=45.0
    )

    payload = {
        "reference_blueprint": req.sound,
        "add_instrumentals": req.add_instrumentals,
        "sections": [
            {
                "index": index,
                "heading": section["heading"],
                "lyric_line_count": len([
                    line for line in section["lines"]
                    if line.strip()
                ])
            }
            for index, section in enumerate(sections)
        ]
    }

    try:
        response = await client.chat.completions.create(
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
            response.choices[0].message.content or "{}"
        )

        arrangements = data.get("sections")

        if not isinstance(arrangements, list):
            raise ValueError("Missing production sections")

        if len(arrangements) != len(sections):
            raise ValueError("Production section count mismatch")

        output = []

        for section, arrangement in zip(
            sections, arrangements
        ):
            if not isinstance(arrangement, dict):
                raise ValueError("Invalid production section")

            heading = section["heading"]

            direction = str(
                arrangement.get("direction") or ""
            ).strip()

            direction = re.sub(
                r"[\[\]\r\n]+", " ", direction
            ).strip()

            # Retain the original section name.
            if direction:
                output.append(
                    f"[{heading} — {direction}]"
                )
            else:
                output.append(f"[{heading}]")

            # Copy the user's original lines unchanged.
            output.extend(section["lines"])

            if req.add_instrumentals:
                instrumental = str(
                    arrangement.get("instrumental_after") or ""
                ).strip()

                instrumental = re.sub(
                    r"[\[\]\r\n]+", " ", instrumental
                ).strip()

                if instrumental:
                    output.append("")
                    output.append(
                        f"[Instrumental — {instrumental}]"
                    )

        tagged = "\n".join(output)

        if len(tagged) > 5000:
            raise HTTPException(
                422,
                "Production directions exceed Suno's "
                "5,000-character limit. Shorten the "
                "original lyrics or reference blueprint."
            )

        return {
            "tagged_lyrics": tagged,
            "characters": len(tagged),
            "lyrics_preserved": True
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            502,
            f"Lyric arrangement failed: {type(exc).__name__}"
        ) from exc
