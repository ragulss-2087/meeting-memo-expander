import base64
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()


MAX_INLINE_AUDIO_BYTES = 15 * 1024 * 1024

AUDIO_FORMATS = {
    ".wav": ("wav", "audio/wav"),
    ".mp3": ("mp3", "audio/mp3"),
    ".mpeg": ("mp3", "audio/mpeg"),
    ".mpga": ("mp3", "audio/mpeg"),
    ".aiff": ("aiff", "audio/aiff"),
    ".aac": ("aac", "audio/aac"),
    ".ogg": ("ogg", "audio/ogg"),
    ".oga": ("ogg", "audio/ogg"),
    ".flac": ("flac", "audio/flac"),
    ".m4a": ("m4a", "audio/m4a"),
    ".webm": ("webm", "audio/webm"),
    ".opus": ("opus", "audio/opus"),
}


def _audio_format(filename, content_type):
    suffix = Path(filename or "").suffix.lower()
    if suffix in AUDIO_FORMATS:
        return AUDIO_FORMATS[suffix]

    mime_type = (content_type or "").split(";")[0].strip().lower()
    for audio_format, expected_mime in AUDIO_FORMATS.values():
        if mime_type == expected_mime:
            return audio_format, mime_type

    raise ValueError(
        "Unsupported audio format. Use WAV, MP3, M4A, AAC, OGG, FLAC, AIFF, or WebM."
    )


async def transcribe(audio_bytes, filename="audio.webm", content_type=None):
    key = os.getenv("STT_API_KEY", "").strip() or os.getenv("LLM_API_KEY", "").strip()
    base = (
        os.getenv("STT_BASE_URL", "").strip()
        or os.getenv(
            "LLM_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        ).strip()
    ).rstrip("/")

    if not key:
        raise RuntimeError("No STT_API_KEY or LLM_API_KEY is configured.")
    if not audio_bytes:
        raise ValueError("The selected audio file is empty.")

    if "generativelanguage.googleapis.com" in base:
        audio_format, _ = _audio_format(filename, content_type)
        model = os.getenv("STT_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Transcribe this audio file."},
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": base64.b64encode(audio_bytes).decode("ascii"),
                                "format": audio_format,
                            },
                        },
                    ],
                }
            ],
        }
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
        try:
            return result["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, AttributeError, TypeError) as exc:
            raise RuntimeError("The transcription service returned no transcript.") from exc

    model = os.getenv("STT_MODEL", "whisper-1").strip() or "whisper-1"
    mime_type = content_type or "application/octet-stream"
    files = {"file": (filename or "audio.webm", audio_bytes, mime_type)}
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            f"{base}/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            data={"model": model},
            files=files,
        )
        response.raise_for_status()
        return response.json().get("text", "").strip()
