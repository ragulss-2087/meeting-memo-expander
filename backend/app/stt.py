import base64
import os

import httpx
from dotenv import load_dotenv
load_dotenv()

async def transcribe(data, filename="audio.webm", content_type="application/octet-stream"):
    key = os.getenv("STT_API_KEY", "").strip() or os.getenv("LLM_API_KEY", "").strip()
    base = os.getenv("STT_BASE_URL", "").strip() or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("STT_MODEL", "whisper-1")
    if not key:
        raise RuntimeError("No STT_API_KEY or LLM_API_KEY is configured.")
    if "generativelanguage.googleapis.com" in base:
        # Gemini does not implement the OpenAI /audio/transcriptions route.
        # Send the audio through Gemini's native generateContent endpoint.
        gemini_model = model if model and model != "whisper-1" else "gemini-3.6-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent"
        payload = {
            "contents": [{
                "parts": [
                    {"text": "Transcribe the spoken words in this audio accurately. Return only the transcript."},
                    {"inline_data": {
                        "mime_type": content_type or "audio/webm",
                        "data": base64.b64encode(data).decode("ascii"),
                    }},
                ]
            }]
        }
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(url, params={"key": key}, json=payload)
            response.raise_for_status()
            result = response.json()
        parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return "\n".join(part.get("text", "") for part in parts if part.get("text"))

    files = {"file": (filename or "audio.webm", data, content_type or "application/octet-stream")}
    form = {"model": model}
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            f"{base.rstrip('/')}/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            data=form,
            files=files,
        )
        response.raise_for_status()
        return response.json().get("text", "")
