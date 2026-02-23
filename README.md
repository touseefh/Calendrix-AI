# Calendrix AI — Voice Scheduling Assistant

A real-time event scheduling assistant that conducts a natural conversation to collect event details and creates confirmed calendar events directly in Google Calendar. Built with Flask, OpenAI GPT-4o, Whisper, and the Google Calendar API.

---

## Table of Contents

- [Overview](#overview)
- [Test Demo](#test-demo)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [AI & API Integrations](#ai--api-integrations)
- [How to Run Locally](#how-to-run-locally)
- [How to Test the Agent](#how-to-test-the-agent)
- [Environment Variables](#environment-variables)
- [Project Structure](#project-structure)

---

## Overview

Calendrix AI is a voice-first scheduling assistant. The user opens the web interface, speaks or types naturally, and the AI conducts a structured conversation to gather:

1. Full name
2. Preferred date
3. Time range (start and end)
4. Event title

Once all details are confirmed by the user, Calendrix AI creates a real Google Calendar event via a Service Account — no OAuth popup, no manual login required. The confirmed event link is returned immediately in the chat.

---

## Test Demo



To test locally, follow the [How to Run Locally](#how-to-run-locally) section below.

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Backend | Python 3.11 + Flask | Lightweight, fast to iterate, excellent OpenAI and Google SDK support |
| AI Conversation | OpenAI GPT-4o | Best-in-class instruction following; reliably extracts structured JSON from natural conversation |
| Speech-to-Text | OpenAI Whisper (whisper-1) | Accurate multilingual transcription, works directly with browser audio blobs |
| Text-to-Speech | OpenAI TTS-1 (nova voice) | Natural-sounding voice output, low latency, streams as audio/mpeg |
| Calendar | Google Calendar API v3 | Industry standard; Service Account auth avoids per-user OAuth |
| Auth | Google Service Account + JSON key | No user login required; the assistant acts as a bot with delegated calendar access |
| Database | SQLite | Zero-config local persistence for booking history |
| Frontend | Vanilla HTML/CSS/JS | No framework overhead; MediaRecorder API handles mic input natively |
| Environment | python-dotenv | Keeps secrets out of source code |

---

## Architecture

```
Browser (HTML/CSS/JS)
    |
    |-- Text input / MediaRecorder (mic)
    |
    v
Flask Backend (app.py)
    |
    |-- /api/start     --> initialise session, return greeting
    |-- /api/chat      --> GPT-4o conversation turn
    |-- /api/voice     --> Whisper STT --> GPT-4o conversation turn
    |-- /api/tts       --> OpenAI TTS-1 --> audio/mpeg stream
    |-- /api/confirm   --> validate times --> Google Calendar API --> save to SQLite
    |-- /api/bookings  --> read recent events from SQLite
    |
    v
OpenAI API (GPT-4o, Whisper, TTS-1)
    |
Google Calendar API v3 (Service Account)
    |
SQLite (scheduler.db)
```

---

## AI & API Integrations

### GPT-4o — Conversation Engine

GPT-4o drives the entire conversation flow. It is given a strict system prompt that instructs it to:

- Collect name, date, time range, and event title one question at a time
- Always confirm details before outputting structured JSON
- Output a single JSON block only after the user explicitly confirms

**Model:** `gpt-4o`

### Whisper — Speech-to-Text

**Model:** `whisper-1`
**Audio format:** `audio/webm;codecs=opus` (Chrome/Edge) or `audio/webm` (Firefox)

### TTS-1 — Text-to-Speech

**Model:** `tts-1`
**Voice:** nova
**Format:** audio/mpeg

**Critical fix:** Google Calendar events use `timeZone: "Asia/Karachi"` (configurable via `USER_TIMEZONE` env var). Previously using `"UTC"` caused events to appear shifted by the local UTC offset.

---
### Event Body Sent to Google

```json
{
  "summary": "Event Title",
  "description": "Scheduled via Calendrix AI\nOrganized for: Name",
  "start": { "dateTime": "2026-02-25T14:00:00", "timeZone": "Asia/Karachi" },
  "end":   { "dateTime": "2026-02-25T17:00:00", "timeZone": "Asia/Karachi" },
  "reminders": {
    "useDefault": false,
    "overrides": [
      { "method": "popup", "minutes": 15 },
      { "method": "email", "minutes": 60 }
    ]
  }
}
```

The response includes the event `htmlLink` which is returned to the user as a clickable "Open in Google Calendar" button.

---

## How to Run Locally

### Prerequisites

- Python 3.10 or higher
- pip
- A Google Cloud project with the Calendar API enabled
- An OpenAI API key

### Step 1 — Clone the Repository

```bash
git clone https://github.com/touseefh/Calendrix-AI.git
cd Calendrix-AI
```

### Step 2 — Install Dependencies

```bash
pip install -r requirements.txt
```

`requirements.txt` includes:

```
flask
openai
google-auth
google-auth-httplib2
google-api-python-client
python-dotenv
```

### Step 3 — Set Up Google Cloud

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or use an existing one)
3. In the left menu go to **APIs & Services > Library**
4. Search for **Google Calendar API** and click **Enable**
5. Go to **APIs & Services > Credentials**
6. Click **Create Credentials > Service Account**
7. Give it a name (e.g. `calendrix-bot`) and click **Create and Continue**
8. Skip optional role assignment, click **Done**
9. Click on the Service Account you just created
10. Go to the **Keys** tab
11. Click **Add Key > Create new key > JSON**
12. The JSON file downloads automatically — keep it safe

### Step 4 — Share Your Calendar with the Service Account

1. Go to [calendar.google.com](https://calendar.google.com)
2. In the left panel, find your calendar and click the three-dot menu
3. Click **Settings and sharing**
4. Scroll to **Share with specific people or groups**
5. Click **Add people**
6. Enter the Service Account email (found in the JSON file as `client_email`, e.g. `calendrix-bot@your-project.iam.gserviceaccount.com`)
7. Set permission to **Make changes to events**
8. Click **Send**

### Step 5 — Create the .env File

Create a file named `.env` in the project root:

```env
OPENAI_API_KEY=sk-proj-your-key-here
GOOGLE_CALENDAR_ID=your-email@gmail.com
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account","project_id":"...entire JSON on one line..."}
SECRET_KEY=any-random-string
USER_TIMEZONE=Asia/Karachi
```

For `GOOGLE_SERVICE_ACCOUNT_JSON`, open the downloaded JSON file, remove all newlines, and paste the entire thing as a single line value.

**Common timezone values:**

| Region | Value |
|---|---|
| Pakistan | Asia/Karachi |
| India | Asia/Kolkata |
| UAE | Asia/Dubai |
| UK | Europe/London |
| US Eastern | America/New_York |
| US Pacific | America/Los_Angeles |

### Step 6 — Run the Application

```bash
python app.py
```


### Step 7 — Open the Application

Open your browser and go to:

```
http://localhost:5000
```

---

## How to Test the Agent

### Text-Based Test

1. Open `http://localhost:5000`
2. Calendrix AI will greet you and ask for your name
3. Type your name and press Enter
4. Follow the conversation — provide a date, time range, and event title
5. When Calendrix AI shows the event summary card, click **Schedule Event**
6. The event is created and a link to Google Calendar appears

### Voice-Based Test

1. Click the microphone button in the chat input area
2. Speak your response naturally (e.g. "My name is Babar Azam")
3. Click the microphone button again to stop recording
4. Calendrix AI will transcribe your speech and respond — also in voice
5. Continue the conversation by voice or switch to typing at any time


### Example Conversation Flow

```
Calendrix AI: Hello. I am Calendrix AI. May I have your name?
You:          My name is Touseef
Calendrix AI: Good to meet you, Touseef. What date works for your event?
You:          Next Monday
Calendrix AI: What time? For example: 4 PM to 6 PM
You:          2 PM to 5 PM
Calendrix AI: What would you like to call this event?
You:          Product Review
Calendrix AI: Perfect. Product Review for Touseef on Monday, February 23, 2026 from 2:00 PM to 5:00 PM. Shall I create this event?
You:          Yes
Calendrix AI: Your event "Product Review" has been scheduled for Monday, February 23, 2026 from 2:00 PM to 5:00 PM.
```

### What to Verify

- The event appears in Google Calendar at the correct date and time (not shifted)
- The event title, name, and time range match what you said
- Reminders are set (15 min popup, 60 min email)
- The event link opens the correct calendar entry

### Troubleshooting

**"Could not transcribe" error**
Verify your `OPENAI_API_KEY` is set correctly in `.env` and has credits available.

**Calendar events appear at wrong time**
Confirm `USER_TIMEZONE` in `.env` matches your local timezone. See timezone table above.

**"Calendar error" on confirm**
The Service Account email has not been granted access to your calendar. Repeat Step 4.


---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key (sk-proj-...) |
| `GOOGLE_CALENDAR_ID` | Yes | Your Gmail address or calendar ID |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Yes | Full Service Account JSON as a single-line string |
| `SECRET_KEY` | Yes | Any random string for Flask session encryption |
| `USER_TIMEZONE` | Yes | Your local timezone (e.g. Asia/Karachi) |

---

## Project Structure

```
calendrix-ai/
├── app.py                  # Flask backend — all routes and logic
├── requirements.txt        # Python dependencies
├── .env                    # Secrets — never commit this file
├── .gitignore              # Excludes .env and scheduler.db
├── scheduler.db            # SQLite database — auto-created on first run
├── templates/
│   └── index.html          # Full frontend — UI, voice recording, chat
└── README.md               # This file
```
