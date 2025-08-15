import json
import os
from io import BytesIO
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import Response

from openai import OpenAI

# ------------- Config and setup -------------

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("WARNING: OPENAI_API_KEY is not set. Set it in your environment or a .env file.")

client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI(title="Healthcare Translation AI (Python)")

# Serve static assets
app.mount("/static", StaticFiles(directory="static"), name="static")

# CORS (same-origin by default; keep permissive if you need to host front-end separately)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For demo; restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MEDICAL_SYSTEM_PROMPT = """
You are a medical-domain translation assistant.
- Correct misrecognized medical terms in the source transcript.
- Preserve clinical meaning, dosages, measurements, lab values, vital signs, names, and dates.
- Expand unclear acronyms only if unambiguous; otherwise keep original and add expansion in parentheses.
- Keep formatting simple. No markdown.
- Return strict JSON with fields: corrected_source, translation.
""".strip()


def no_store_headers() -> dict:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0, s-maxage=0"
    }


# ------------- Routes -------------

@app.get("/")
def root():
    # Serve the static SPA
    return FileResponse("static/index.html", headers=no_store_headers())


@app.post("/api/translate")
async def translate(payload: dict):
    """
    Body: { text: string, sourceLang: string (BCP-47), targetLang: string (BCP-47) }
    """
    headers = no_store_headers()
    text = payload.get("text", "")
    source_lang = payload.get("sourceLang", "auto")
    target_lang = payload.get("targetLang")

    if not text or not target_lang:
        return JSONResponse({"error": "Missing text or targetLang"}, status_code=400, headers=headers)

    try:
        # Use the Responses API with JSON schema to ensure structured output
        resp = client.responses.create(
            model="gpt-4o-mini",
            temperature=0.2,
            reasoning={"effort": "medium"},
            input=[
                {"role": "system", "content": MEDICAL_SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {
                        "type": "text",
                        "text": f"Source language (BCP-47): {source_lang}\nTarget language (BCP-47): {target_lang}\n\nText:\n{text}"
                    }
                ]}
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "MedicalTranslation",
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "corrected_source": {"type": "string"},
                            "translation": {"type": "string"}
                        },
                        "required": ["corrected_source", "translation"]
                    }
                }
            }
        )

        parsed: Optional[dict] = None

        # Prefer output_text helper if present
        out_text = getattr(resp, "output_text", None)
        if out_text:
            parsed = json.loads(out_text)
        else:
            # Fallback: try to find output_text-like content in 'output'
            output = getattr(resp, "output", None)
            if isinstance(output, list):
                for item in output:
                    if item.get("type") == "output_text" and "text" in item:
                        parsed = json.loads(item["text"])
                        break

        if not parsed:
            raise ValueError("Failed to parse translation output")

        return JSONResponse(parsed, status_code=200, headers=headers)
    except Exception as e:
        print("Translate error:", str(e))
        return JSONResponse({"error": "Translation failed"}, status_code=500, headers=headers)


@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...), sourceLang: str = Form("en-US")):
    """
    Multipart form-data:
      - audio: recorded audio (e.g., audio/webm)
      - sourceLang: optional hint (BCP-47)
    """
    headers = no_store_headers()
    try:
        # Read bytes for safety across SDKs
        blob = await audio.read()
        file_like = BytesIO(blob)

        text: Optional[str] = None

        # Try gpt-4o-transcribe first
        try:
            res = client.audio.transcriptions.create(
                model="gpt-4o-transcribe",
                file=file_like
            )
            # Some SDKs return an object with 'text' attribute
            text = getattr(res, "text", None)
        except Exception:
            # Reset buffer for second attempt
            file_like.seek(0)
            res2 = client.audio.transcriptions.create(
                model="whisper-1",
                file=file_like
            )
            text = getattr(res2, "text", None)

        if not text:
            raise ValueError("No transcription text received")

        return JSONResponse({"text": text}, status_code=200, headers=headers)
    except Exception as e:
        print("Transcribe error:", str(e))
        return JSONResponse({"error": "Transcription failed"}, status_code=500, headers=headers)