# Signal Forge — AI Suno Prompt Machine

A GitHub Pages frontend + Python/FastAPI AI backend for original Suno style prompts. Includes a **Cryptid Static** preset, copyable production tags, reference-song inference, and audio-feature analysis.

## Architecture

```text
Phone / browser → GitHub Pages (frontend/)
                         │ HTTPS requests
                         ▼
               FastAPI server (backend/)
                 ├─ OpenAI API (secret key on server only)
                 └─ librosa (uploaded audio measurements)
```

**Important:** GitHub Pages does not execute Python or protect secret keys. Host `backend/` on a Python-capable service (Render, Railway, Fly.io, VPS, etc.). Those services and OpenAI API calls may cost money. A ChatGPT subscription does not include API credits.

## 1. Run locally

Python 3.11 recommended. Install FFmpeg if you want MP3 support.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export OPENAI_API_KEY='YOUR_KEY'  # Windows PowerShell: $env:OPENAI_API_KEY='YOUR_KEY'
uvicorn main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
python -m http.server 8080
```

Visit `http://localhost:8080` and leave Backend URL set to `http://localhost:8000`.

## 2. Publish frontend on GitHub Pages

1. Create a new GitHub repository and upload these project files.
2. Open **Settings → Pages → Build and deployment**.
3. Choose **Deploy from a branch**, select `main` and `/docs` (see next step) or place the `frontend/` files at repository root and choose `/ (root)`.
4. Easiest: copy the three files from `frontend/` to a folder named `docs/` at repository root, commit, and select `/docs` in Pages settings.
5. Your site will appear at `https://YOUR-USERNAME.github.io/REPO-NAME/`.

## 3. Deploy the backend

1. Create a Python web service on a backend hosting provider, pointing at the repository's `backend` directory (or use the included Dockerfile with `backend/` as build context).
2. For a native Python deployment, build with `pip install -r requirements.txt` and start with `uvicorn main:app --host 0.0.0.0 --port $PORT`.
3. Set private environment variables in the host dashboard (NOT in GitHub files):
   - `OPENAI_API_KEY` — your OpenAI API key.
   - `OPENAI_MODEL` — default `gpt-4o-mini` (check model availability for your account).
   - `ALLOWED_ORIGINS` — your exact GitHub Pages origin, e.g. `https://YOUR-USERNAME.github.io` (no path).
4. Confirm `https://YOUR-BACKEND/health` returns `{"ok":true}`.
5. Open your GitHub Pages site, paste `https://YOUR-BACKEND` into **Backend URL** at the bottom, and generate a prompt.

## How analysis works

- **Song title + artist:** AI uses general knowledge and your description; it **does not fetch or listen to the recording**. It must label uncertain assumptions.
- **Uploaded audio:** backend analyzes up to the first 90 seconds (12 MB maximum), estimating BPM, RMS energy/dynamics, spectral brightness, and zero-crossing rate. AI translates these *measurements* plus your preferences into a prompt. It does **not** transcribe, fingerprint, recognize the song, or reliably detect individual instruments or vocal identity.
- **Suno outputs:** original style description capped at 1,000 characters, plus section-level production tags. Never copies lyrics or melodies.

## Security before sharing publicly

This starter is best for **personal use**. The frontend contains no API key, but the backend endpoints are otherwise unauthenticated. **Do not publish the backend URL for unrestricted use**: anyone who finds it could spend your API credits. Before opening it to others, add server-side authentication, per-user rate limiting, request quotas, cost caps and abuse monitoring. CORS is not authentication. Use HTTPS for public deployment. Do not commit `.env` files or API keys. Uploaded audio is processed in memory and not intentionally stored; the extracted feature summary is sent to the configured AI provider.

## Troubleshooting

- **503:** missing API key on backend.
- **CORS error:** set `ALLOWED_ORIGINS` to the GitHub Pages origin, not its `/repo-name` path.
- **422 on audio:** try WAV or install FFmpeg; some formats are not supported by your host.
- **502:** AI provider or model error; check backend logs.
- **Large upload:** use a short excerpt under 12 MB.

## Customization

Change the `SYSTEM` instructions in `backend/main.py` to adjust the Cryptid Static preset. Change colors/layout in `frontend/style.css`. This is an original implementation, not a copy of another website's code or proprietary features.
