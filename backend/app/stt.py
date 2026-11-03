import os, httpx
from dotenv import load_dotenv
load_dotenv()

async def transcribe(upload):
    key = os.getenv("STT_API_KEY", "").strip() or os.getenv("LLM_API_KEY", "").strip()
    base = os.getenv("STT_BASE_URL", "").strip() or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("STT_MODEL", "whisper-1")
    if not key:
        raise RuntimeError("No STT_API_KEY or LLM_API_KEY is configured.")
    data = await upload.read()
    files = {"file": (upload.filename or "audio.webm", data, upload.content_type or "application/octet-stream")}
    form = {"model": model}
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(f"{base}/audio/transcriptions",
            headers={"Authorization":f"Bearer {key}"}, data=form, files=files)
        r.raise_for_status()
        return r.json().get("text","")
