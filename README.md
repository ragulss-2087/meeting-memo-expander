# Meeting Memo Expander 

A general-purpose AI meeting intelligence platform for **every meeting and every industry**. It is not limited to IT, software, or full-stack meetings.

## What it does

For each individual meeting, the system can:
- store a meeting title and transcript
- analyze the meeting with an OpenAI-compatible LLM endpoint (Gemini supported)
- generate a summary and discussion points
- extract decisions
- extract action items with owners and deadlines when explicitly available
- identify risks and unresolved issues
- generate follow-up questions
- search meeting memory
- ask questions about a selected meeting
- hold a browser-based continuous voice conversation about the selected meeting
- speak AI answers aloud
- export meeting analysis to DOCX or PDF
- delete a meeting together with its tasks and decisions
- keep projects and meeting records private to the signed-in account

## Accounts and private data

Create an account from the sign-in screen. Each new account gets its own
`My Project`; projects, meetings, tasks, decisions, search, and exports are
limited to that account. Passwords are stored as salted PBKDF2 hashes, and
sign-in sessions expire after 14 days.

The backend adds the account and session tables and adds project ownership to
an existing database when it starts. Existing projects that were created
before accounts existed have no owner and are intentionally not shown to new
accounts. This avoids assigning shared meeting content to the wrong person.

## Suitable meeting examples

Healthcare, education, banking, finance, legal, construction, manufacturing, retail, hospitality, government, sales, marketing, consulting, HR, operations, IT, software, startups, and other organizations. The AI prompt is explicitly industry-agnostic and must not assume a software-development context.

## Project structure

```text
MeetingMemoExpander_Level3/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── db.py
│   │   ├── llm.py
│   │   ├── stt.py
│   │   └── exporter.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── main.jsx
│   │   └── styles.css
│   ├── package.json
│   └── index.html
├── .gitignore
└── README.md
```

## Requirements

- Python 3.10+ (Python 3.12 is recommended for this project)
- Node.js 18+
- npm
- A Gemini/OpenAI-compatible API key for AI analysis and meeting Q&A

## 1. Backend setup — Windows

Open a terminal in `backend`:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Open `backend/.env` and add your own API key. **Never commit or share a real key.**

Example Gemini configuration:

```env
LLM_API_KEY=YOUR_GEMINI_KEY
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_MODEL=gemini-3.6-flash

STT_API_KEY=YOUR_GEMINI_KEY
STT_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
STT_MODEL=gemini-3.6-flash

DATABASE_PATH=meeting_memo.db
```

Start the backend:

```powershell
uvicorn app.main:app --reload --port 8000
```

Swagger API documentation:
`http://127.0.0.1:8000/docs`

## 2. Frontend setup

Open a second terminal in `frontend`:

```powershell
npm install
npm run dev
```

Open the Vite URL, normally `http://localhost:5173`.

## 3. Voice agent

The live meeting voice agent runs in the browser using Web Speech API recognition and browser text-to-speech. Google Chrome is recommended. Select/open a meeting, start the voice conversation once, and continue asking follow-up questions until Stop is pressed.

## 4. API features

- `GET /api/health`
- `GET /api/projects`
- `POST /api/projects`
- `GET /api/meetings`
- `GET /api/meetings/{id}`
- `POST /api/meetings`
- `DELETE /api/meetings/{id}`
- `POST /api/transcribe`
- `GET /api/tasks`
- `PATCH /api/tasks/{id}`
- `GET /api/decisions`
- `GET /api/search`
- `POST /api/meetings/{id}/ask`
- `GET /api/meetings/{id}/export/docx`
- `GET /api/meetings/{id}/export/pdf`

## Deployment notes

This project is ready for final local integration testing, but a public production deployment should additionally use a production database, HTTPS, authentication/authorization, server-side rate limiting, secure secret management, file-size/type validation, and a production ASGI/server configuration.

The repository intentionally does **not** include a real `.env`, API key, `.venv`, or generated local SQLite database.


## Password reset email setup

To enable **Forgot password**, configure SMTP in `backend/.env`. For Gmail, use `smtp.gmail.com` on port `587`, enable TLS, and use a Google App Password for `SMTP_PASSWORD` (not your normal account password). Set `SMTP_USER` and `SMTP_FROM` to the sender address. Set `FRONTEND_URL` to `http://localhost:5173` for local use, or to your deployed frontend URL in production. Reset links expire after 30 minutes and can only be used once. Keep mail credentials private and configure production values in the hosting provider's environment settings.
