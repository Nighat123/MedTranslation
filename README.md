# Healthcare Translation AI (Python + HTML/CSS/JS)

A mobile-first web app providing real-time speech-to-text, medical-aware AI correction, translation, and audio playback for multilingual patient–provider conversations.

## Features

- Real-time transcription via Web Speech API (when supported by the browser).
- Server fallback: press-and-hold to record, using OpenAI for transcription (`gpt-4o-transcribe`, fallback `whisper-1`).
- Medical-aware correction and translation via OpenAI (`gpt-4o-mini`) with strict JSON schema.
- Dual transcript panes and "Speak" button using Web Speech Synthesis.
- Mobile-first, responsive UI.
- Basic privacy: no persistence; `no-store` caching headers; limited logs.

## Requirements

- Python 3.10+
- OpenAI API key

## Quick Start

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set your OpenAI API key:
   - Copy `.env.example` to `.env` or export in your shell:
     ```bash
     export OPENAI_API_KEY=sk-...
     ```

3. Run the server:
   ```bash
   uvicorn app:app --host 0.0.0.0 --port 8000 --reload
   ```

4. Open:
   - http://localhost:8000

## Usage

- Choose Input and Output languages.
- If your browser supports it, keep "Use browser speech recognition" checked to get live, continuous transcription.
- Otherwise, uncheck it and press-and-hold the mic button to record audio that is transcribed on the server when released.
- Watch the Original and Translated panes update in real time.
- Tap "Speak" to hear the translated text.

## Security & Privacy

- No data is stored server-side. API responses carry `Cache-Control: no-store`.
- Avoid logging PHI. This prototype logs only high-level errors.
- Use HTTPS in production (your hosting provider typically terminates TLS).

## Testing & QA

- Validate:
  - Live transcription starts, updates, and stops as expected (Chrome recommended).
  - Server fallback records and transcribes when the mic button is released.
  - "AI-corrected medical terms" panel appears when corrections differ from the original.
  - Translation accuracy for medications, dosages, and clinical phrases.
  - "Speak" plays audio in the target language voice (voice availability depends on OS/browser).
  - Error states: permission denied, network errors, model errors.

## Deployment

- Any platform that can run FastAPI/uvicorn works (Render, Railway, Fly.io, AWS, etc.).
- For Vercel, consider a Node/Next.js front-end with Python serverless functions or a containerized deployment elsewhere.
- Ensure `OPENAI_API_KEY` is set in your hosting environment.

## Notes

- Web Speech Recognition support varies by browser; Chrome has the best support. Safari often lacks recognition but supports Speech Synthesis.
- For consistent TTS voices across browsers, consider integrating a cloud TTS service later.

## Disclaimer

This prototype is for demonstration only and does not replace professional medical interpretation. Validate translations before clinical use.