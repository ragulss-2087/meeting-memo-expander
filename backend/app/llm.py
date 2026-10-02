import os
import json
import asyncio
import httpx


async def _chat(prompt: str):
    api_key = os.getenv("LLM_API_KEY")

    base_url = os.getenv(
        "LLM_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta/openai/"
    )

    model = os.getenv(
        "LLM_MODEL",
        "gemini-3.6-flash"
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "response_format": {
            "type": "json_object"
        }
    }

    async with httpx.AsyncClient(timeout=60.0) as client:

        for attempt in range(3):

            try:

                response = await client.post(
                    f"{base_url}chat/completions",
                    headers=headers,
                    json=payload
                )

                print("GEMINI STATUS:", response.status_code)

                if response.status_code >= 400:
                    print(
                        "GEMINI RESPONSE:",
                        response.text
                    )

                # --------------------------------
                # SUCCESS
                # --------------------------------

                if response.status_code == 200:
                    data = response.json()

                    return data["choices"][0]["message"]["content"]

                # --------------------------------
                # QUOTA EXCEEDED
                # --------------------------------

                if response.status_code == 429:

                    print(
                        "Gemini quota exceeded."
                    )

                    raise RuntimeError(
                        "Gemini API quota exceeded. "
                        "Please wait for the quota to reset "
                        "before trying again."
                    )

                # --------------------------------
                # TEMPORARY SERVER ERROR
                # --------------------------------

                if response.status_code == 503:

                    if attempt < 2:

                        wait_time = 5 * (attempt + 1)

                        print(
                            f"Gemini temporarily unavailable. "
                            f"Retrying in {wait_time} seconds..."
                        )

                        await asyncio.sleep(
                            wait_time
                        )

                        continue

                    raise RuntimeError(
                        "Gemini is temporarily unavailable. "
                        "Please try again later."
                    )

                # --------------------------------
                # OTHER API ERROR
                # --------------------------------

                try:
                    error_data = response.json()
                    error_message = error_data.get(
                        "error",
                        {}
                    ).get(
                        "message",
                        response.text
                    )
                except Exception:
                    error_message = response.text

                raise RuntimeError(
                    f"Gemini API error "
                    f"({response.status_code}): "
                    f"{error_message}"
                )

            except httpx.RequestError as e:

                if attempt < 2:

                    wait_time = 3 * (attempt + 1)

                    print(
                        "Network error while contacting Gemini. "
                        f"Retrying in {wait_time} seconds..."
                    )

                    await asyncio.sleep(
                        wait_time
                    )

                    continue

                raise RuntimeError(
                    "Could not connect to Gemini API. "
                    f"Network error: {e}"
                )


async def analyze(transcript: str):

    prompt = f"""
Analyze the following meeting transcript as a general-purpose meeting intelligence system.
The meeting may belong to ANY industry or organization, including healthcare, education,
finance, legal, construction, manufacturing, retail, hospitality, government, sales,
marketing, consulting, IT, or any other domain. Do not assume the meeting is technical
or related to software development. Extract only information supported by the transcript.

Return ONLY valid JSON with these fields:

- summary: concise meeting summary
- discussion_points: important topics discussed
- decisions: decisions actually made; each item may contain decision and context
- action_items: concrete tasks; each item may contain title, owner, and deadline. Do not invent an owner or deadline.
- risks: risks, blockers, concerns, or dependencies explicitly mentioned or clearly stated
- unresolved_issues: issues that remain open or need follow-up
- follow_up_questions: useful questions that remain unanswered from the meeting

Transcript:

{transcript}
"""

    content = await _chat(prompt)

    return json.loads(content)


async def answer_question(
    question: str,
    context: str,
    history=None
):
    history = history or []

    history_text = ""

    for message in history:
        role = message.get("role", "user")
        content = message.get("content", "")

        history_text += (
            f"{role}: {content}\n"
        )

    prompt = f"""
Answer the user's question using ONLY the meeting information provided below.

Meeting information:

{context}

Previous conversation:

{history_text}

Current user question:

{question}

Return ONLY valid JSON with this field:

- answer
"""

    content = await _chat(prompt)

    return json.loads(content)