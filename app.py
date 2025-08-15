import io
import os
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Load environment variables from a local .env file (if present)
# Requires: python-dotenv (pip install python-dotenv)
try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")
except Exception as e:
    logging.getLogger(__name__).warning("Could not load .env automatically: %s", e)

# OpenAI SDK (pip install 'openai>=1.40.0')
from openai import OpenAI, OpenAIError

# --- Configuration ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")  # optional, e.g., proxy or Azure-compatible gateway
LLM_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
STT_MODEL = os.getenv("STT_MODEL", "gpt-4o-transcribe")  # or "whisper-1"
TTS_MODEL = os.getenv("TTS_MODEL", "gpt-4o-mini-tts")
DEFAULT_TTS_VOICE = os.getenv("TTS_VOICE", "alloy")

# Lazily create the OpenAI client when needed, so app can start without a key
_client: Optional[OpenAI] = None


def get_openai_client() -> OpenAI:
    global _client
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not set. Add it to .env or the environment.",
        )
    if _client is None:
        _client = OpenAI(api_key=api_key, base_url=OPENAI_BASE_URL) if OPENAI_BASE_URL else OpenAI(api_key=api_key)
    return _client


app = FastAPI(title="Healthcare Translation Web App", version="1.0.0")

# CORS: For prototypes you may allow '*', tighten in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Static files ---
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


@app.get("/")
def root():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse(
        {
            "message": "Healthcare Translation Web App backend is running.",
            "docs": "/docs",
            "health": "/health",
            "static_index_hint": "Place an index.html at ./static/index.html to serve a homepage.",
        }
    )


# --- Schemas ---
class TranslateRequest(BaseModel):
    text: str = Field(..., description="Source text to translate")
    source_lang: Optional[str] = Field(None, description="Source language (auto if omitted)")
    target_lang: str = Field(..., description="Target language to translate into")


class TranslateResponse(BaseModel):
    translated_text: str
    model: str


class TTSRequest(BaseModel):
    text: str = Field(..., description="Text to synthesize to speech")
    voice: Optional[str] = Field(None, description="TTS voice to use")
    format: Optional[str] = Field("mp3", description="Audio format: mp3|wav|ogg")


# --- Routes ---
@app.get("/health")
def health():
    return {
        "status": "ok",
        "models": {"llm": LLM_MODEL, "stt": STT_MODEL, "tts": TTS_MODEL},
        "has_api_key": bool(os.getenv("OPENAI_API_KEY")),
    }


@app.post("/translate", response_model=TranslateResponse)
async def translate(req: TranslateRequest):
    """Translate text with medical terminology fidelity using the selected LLM."""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")

    try:
        client = get_openai_client()
        system = (
            "You are a professional medical translator. "
            "Translate the user's text into the target language with high fidelity, "
            "preserving medical terminology accurately. "
            "Keep the output concise and natural for patient-provider communication. "
            "Do not add explanations—return only the translation."
        )

        user_prompt = f"Target language: {req.target_lang}\n"
        if req.source_lang:
            user_prompt += f"Source language: {req.source_lang}\n"
        user_prompt += f"Text:\n{req.text}"

        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        translated = (resp.choices[0].message.content or "").strip()
        if not translated:
            raise HTTPException(status_code=502, detail="Empty translation from model")

        return TranslateResponse(translated_text=translated, model=LLM_MODEL)
    except HTTPException:
        raise
    except OpenAIError as e:
        raise HTTPException(status_code=502, detail=f"OpenAI error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/stt")
async def stt(file: UploadFile = File(...)):
    """Speech-to-text fallback endpoint. Accepts audio (webm/mp3/wav/ogg) and returns transcript."""
    try:
        client = get_openai_client()
        data = await file.read()
        bio = io.BytesIO(data)
        # Give the BytesIO a name so the SDK can infer format
        bio.name = file.filename or "audio.webm"
        result = client.audio.transcriptions.create(
            model=STT_MODEL,
            file=bio,
        )
        text = getattr(result, "text", None) or getattr(result, "output_text", None)
        if not text:
            raise HTTPException(status_code=502, detail="STT returned no text")
        return {"text": text, "model": STT_MODEL}
    except HTTPException:
        raise
    except OpenAIError as e:
        raise HTTPException(status_code=502, detail=f"OpenAI STT error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tts")
async def tts(req: TTSRequest):
    """Text-to-speech endpoint. Returns audio bytes (mp3/wav/ogg)."""
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")

    voice = (req.voice or DEFAULT_TTS_VOICE).strip()
    fmt = (req.format or "mp3").lower()
    if fmt not in {"mp3", "wav", "ogg"}:
        raise HTTPException(status_code=400, detail="Invalid format. Use mp3, wav, or ogg")

    try:
        client = get_openai_client()

        # Prefer streaming to avoid buffering large audio in memory
        stream_ctx = client.audio.speech.with_streaming_response.create(
            model=TTS_MODEL,
            voice=voice,
            input=text,
            format=fmt,
        )

        def iterator():
            with stream_ctx as resp:
                for chunk in resp.iter_bytes():
                    yield chunk

        media_type = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "ogg": "audio/ogg",
        }[fmt]
        headers = {"Content-Disposition": f'inline; filename="speech.{fmt}"'}
        return StreamingResponse(iterator(), media_type=media_type, headers=headers)
    except HTTPException:
        raise
    except OpenAIError as e:
        raise HTTPException(status_code=502, detail=f"OpenAI TTS error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "1").lower() in ("1", "true", "yes")

    # Run with: python -m app
    uvicorn.run("app:app", host=host, port=port, reload=reload)