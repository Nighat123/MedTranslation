import os
import base64
import mimetypes
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")  # optional, e.g., a proxy or Azure-compatible endpoint
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Lazily create the OpenAI client when needed so app can start without a key
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


app = FastAPI(title="Medical App", version="1.0.1")

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
            "message": "Welcome to the Medical App",
            "docs": "/docs",
            "health": "/health",
            "static_index_hint": "Place an index.html at ./static/index.html to serve a homepage.",
        }
    )


# --- Schemas ---
class ChatRequest(BaseModel):
    message: str
    system: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = 0.2
    max_tokens: Optional[int] = 512


class ChatReply(BaseModel):
    reply: str
    model: str


class VisionResponse(BaseModel):
    reply: str
    model: str


# --- Routes ---
@app.get("/health")
def health():
    # Don’t force a key just to report health
    return {"status": "ok", "model": DEFAULT_MODEL, "has_api_key": bool(os.getenv("OPENAI_API_KEY"))}


@app.post("/chat", response_model=ChatReply)
async def chat(req: ChatRequest):
    model = req.model or DEFAULT_MODEL
    messages = []
    if req.system:
        messages.append({"role": "system", "content": req.system})
    messages.append({"role": "user", "content": req.message})

    try:
        client = get_openai_client()
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )
        content = resp.choices[0].message.content
        return ChatReply(reply=content, model=model)
    except HTTPException:
        raise
    except OpenAIError as e:
        raise HTTPException(status_code=502, detail=f"OpenAI error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _detect_mime(filename: str, default="application/octet-stream"):
    mime, _ = mimetypes.guess_type(filename)
    return mime or default


@app.post("/vision", response_model=VisionResponse)
async def vision(
    file: UploadFile = File(...),
    prompt: Optional[str] = "Describe this image.",
    model: Optional[str] = None,
    max_tokens: int = 512,
):
    """Send an image and an optional prompt for multimodal analysis."""
    model = model or DEFAULT_MODEL
    try:
        client = get_openai_client()
        data = await file.read()
        mime = file.content_type or _detect_mime(file.filename or "")
        b64 = base64.b64encode(data).decode("utf-8")
        data_url = f"data:{mime};base64,{b64}"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt or "Describe this image."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ]
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
        )
        content = resp.choices[0].message.content
        return VisionResponse(reply=content, model=model)
    except HTTPException:
        raise
    except OpenAIError as e:
        raise HTTPException(status_code=502, detail=f"OpenAI error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            await file.close()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")  # 127.0.0.1 is fine for local browsing
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "1").lower() in ("1", "true", "yes")

    # Run with: python -m app
    uvicorn.run("app:app", host=host, port=port, reload=reload)