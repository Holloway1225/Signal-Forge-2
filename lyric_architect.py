import json
import os
import re
from difflib import SequenceMatcher
from fastapi import APIRouter, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

router = APIRouter()

class LyricRequest(BaseModel):
    lyrics: str = Field(min_length=1, max_length=5000)
    sound: str = Field(min_length=1, max_length=1500)
    preserve_lyrics: bool = True
    add_instrumentals: bool = True

SECTION = re.compile(r'^\s*\[([^\]\n]+)\]\s*$')

def is_tag(line):
    return bool(SECTION.fullmatch(line))

def original_lines(lyrics):
    return [line.strip() for line in lyrics.splitlines() if line.strip() and not is_tag(line)]

def output_lines(lyrics):
    return [line.strip() for line in lyrics.splitlines() if line.strip() and not is_tag(line)]

SYSTEM = '''You are a professional Suno production-tag arranger. Return JSON with one key: tagged_lyrics. Keep every original nonblank lyric line exactly as written, in exactly the same order. Do not add, delete, paraphrase, duplicate, or reorder lyric lines. Preserve original section headings, but you may replace each heading with a bracketed heading that begins with the same section name and adds concise production directions. You may insert new bracket-only instrumental sections between existing sections if requested, but never insert vocal words. Do not use parenthetical spoken cues. All added material must be bracket-only production/section tags. Match the requested custom sound. Keep output under 5000 characters. No markdown fences.'''

@router.post('/api/tag-lyrics')
async def tag_lyrics(req: LyricRequest):
    if not os.getenv('OPENAI_API_KEY'):
        raise HTTPException(503, 'OPENAI_API_KEY is not configured')
    client = AsyncOpenAI(api_key=os.environ['OPENAI_API_KEY'], timeout=45.0)
    try:
        result = await client.chat.completions.create(
            model=os.getenv('OPENAI_MODEL', 'gpt-4o-mini'),
            temperature=0.2,
            response_format={'type':'json_object'},
            messages=[{'role':'system','content':SYSTEM}, {'role':'user','content':json.dumps(req.model_dump())}]
        )
        tagged = json.loads(result.choices[0].message.content or '{}').get('tagged_lyrics')
        if not isinstance(tagged, str):
            raise ValueError('Missing tagged_lyrics')
        if original_lines(req.lyrics) != output_lines(tagged):
            raise HTTPException(422, 'AI changed original lyric lines; no modified lyrics returned. Try again.')
        if not req.add_instrumentals and re.search(r'(?im)^\s*\[(?:instrumental|guitar solo|solo|instrumental chorus)\b', tagged):
            raise HTTPException(422, 'AI added an unwanted instrumental section; try again.')
        if len(tagged) > 5000:
            raise HTTPException(422, 'Tagged lyrics exceed 5000 characters; shorten directions or source lyrics.')
        return {'tagged_lyrics':tagged, 'characters':len(tagged), 'lyrics_preserved':True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f'Lyric tagging failed: {type(exc).__name__}') from exc
