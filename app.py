from dotenv import load_dotenv
load_dotenv()

import os, json, re, sqlite3, datetime, tempfile, urllib.parse
from flask import Flask, render_template, request, jsonify, session, Response

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "calendrix-2024")

OPENAI_API_KEY              = os.environ.get("OPENAI_API_KEY", "").strip()
GOOGLE_CALENDAR_ID          = os.environ.get("GOOGLE_CALENDAR_ID", "primary").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

print(f"\n{'='*52}\n  Calendrix AI\n{'='*52}")
print(f"  OpenAI:   {'YES (' + OPENAI_API_KEY[:12] + '...)' if OPENAI_API_KEY else 'NOT SET'}")
print(f"  Calendar: {GOOGLE_CALENDAR_ID}")
print(f"  SvcAcct:  {'Loaded' if GOOGLE_SERVICE_ACCOUNT_JSON else 'NOT SET'}")
print(f"{'='*52}\n")

def init_db():
    conn = sqlite3.connect("scheduler.db")
    c = conn.cursor()
    c.execute("PRAGMA table_info(bookings)")
    cols = [r[1] for r in c.fetchall()]
    
    if cols and "start_time" not in cols:
        print("Migrating schema...")
        c.execute("DROP TABLE IF EXISTS bookings")
    
    c.execute("""CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, 
        date TEXT, 
        start_time TEXT,
        end_time TEXT,
        title TEXT,
        calendar_event_id TEXT, 
        event_link TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()
    conn.close()
    print("DB ready.")

init_db()

def get_client():
    return OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY and OPENAI_AVAILABLE else None

SYSTEM = """You are Calendrix AI, a scheduling assistant.
Collect ONE AT A TIME: 1) name 2) date 3) time range 4) meeting title.
Ask ONE question per message (max 35 words).
For time, ask: "What time? (e.g., 4 PM to 6 PM or 4:00-6:00)"
After all 4 collected, confirm: "Perfect! [TITLE] for [NAME] on [DATE] from [START] to [END]. Create?"
Only after user confirms (yes/ok/sure/correct), output:
```json
{"name":"NAME","date":"YYYY-MM-DD","start_time":"HH:MM","end_time":"HH:MM","title":"TITLE","confirmed":true}
```
Parse dates: today={TODAY}, tomorrow={TOMORROW}. Times: 2pm=14:00, 9am=09:00.
Today={TODAY}. Tomorrow={TOMORROW}."""

def chat_gpt(messages, user_input):
    client = get_client()
    if not client:
        return demo_chat(messages, user_input)
    today    = datetime.date.today().strftime("%A %B %d %Y")
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%A %B %d %Y")
    sys_msg  = SYSTEM.replace("{TODAY}", today).replace("{TOMORROW}", tomorrow)
    all_msgs = [{"role": "system", "content": sys_msg}] + messages + [{"role": "user", "content": user_input}]
    try:
        r = get_client().chat.completions.create(model="gpt-4o", messages=all_msgs, max_tokens=300, temperature=0.7)
        return r.choices[0].message.content
    except Exception as e:
        return f"Technical issue: {str(e)[:80]}. Please try again."

def do_tts(text):
    client = get_client()
    if not client:
        return None
    clean_text = re.sub(r'```json.*?```', '', text, flags=re.DOTALL)
    clean_text = re.sub(r'\*\*(.*?)\*\*', r'\1', clean_text).strip()
    if not clean_text:
        clean_text = "Got it!"
    try:
        r = client.audio.speech.create(model="tts-1", voice="nova", input=clean_text[:500])
        return r.content
    except Exception as e:
        print(f"TTS error: {e}")
        return None

def do_stt(audio_bytes, filename="rec.webm"):
    client = get_client()
    if not client:
        return None
    try:
        suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_bytes)
            tmp = f.name
        with open(tmp, "rb") as af:
            t = client.audio.transcriptions.create(model="whisper-1", file=af)
        os.unlink(tmp)
        return t.text
    except Exception as e:
        print(f"STT error: {e}")
        return None

def strict_parse_time(s):
    s = str(s).lower().strip()
    
    if "noon" in s or "12 pm" in s or "12pm" in s:
        return "12:00"
    if "midnight" in s or "12 am" in s or "12am" in s:
        return "00:00"
    
    m = re.search(r'(\d{1,2}):?(\d{2})?\s*(am|pm)?', s)
    if m:
        h = int(m.group(1))
        mn = int(m.group(2) or 0)
        ap = m.group(3)
        
        if ap == "pm" and h != 12:
            h += 12
        elif ap == "am" and h == 12:
            h = 0
        elif not ap:
            if h <= 6:
                h += 12
        
        return f"{h:02d}:{mn:02d}"
    
    return "10:00"

def parse_time_range_strict(s):
    s = str(s).lower().strip()
    
    if ' to ' in s:
        parts = s.split(' to ')
    elif ' - ' in s:
        parts = s.split(' - ')
    elif '-' in s and ' ' not in s:
        parts = s.split('-')
    else:
        start = strict_parse_time(s)
        h = int(start.split(':')[0])
        m = start.split(':')[1]
        end_h = h + 1
        if end_h >= 24:
            end_h = 23
        end = f"{end_h:02d}:{m}"
        return start, end
    
    if len(parts) == 2:
        start_time = strict_parse_time(parts[0].strip())
        end_time = strict_parse_time(parts[1].strip())
        return start_time, end_time
    
    start = strict_parse_time(s)
    h = int(start.split(':')[0])
    m = start.split(':')[1]
    end_h = h + 1
    if end_h >= 24:
        end_h = 23
    end = f"{end_h:02d}:{m}"
    return start, end

def make_event(name, date_str, start_time_str, end_time_str, title):
    try:
        start_dt = datetime.datetime.strptime(f"{date_str} {start_time_str}", "%Y-%m-%d %H:%M")
        end_dt   = datetime.datetime.strptime(f"{date_str} {end_time_str}", "%Y-%m-%d %H:%M")
    except:
        return None, "Invalid time format", ""
    
    if end_dt <= start_dt:
        end_dt = end_dt + datetime.timedelta(days=1)
    
    sf = start_dt.strftime("%Y%m%dT%H%M%SZ")
    ef = end_dt.strftime("%Y%m%dT%H%M%SZ")
    share = (f"https://calendar.google.com/calendar/render?action=TEMPLATE"
             f"&text={urllib.parse.quote(title)}&dates={sf}/{ef}"
             f"&details={urllib.parse.quote('Scheduled via Calendrix AI for ' + name)}")

    if not GOOGLE_AVAILABLE or not GOOGLE_SERVICE_ACCOUNT_JSON:
        fid = f"demo_{int(datetime.datetime.now().timestamp())}"
        return fid, "", share

    try:
        sa   = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        cred = service_account.Credentials.from_service_account_info(
            sa, scopes=["https://www.googleapis.com/auth/calendar"])
        svc  = build("calendar", "v3", credentials=cred)
        body = {
            "summary": title,
            "description": f"Scheduled via Calendrix AI\nOrganized for: {name}",
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "UTC"},
            "end":   {"dateTime": end_dt.isoformat(),   "timeZone": "UTC"},
            "reminders": {"useDefault": False, "overrides": [
                {"method": "popup",  "minutes": 15},
                {"method": "email",  "minutes": 60}]}
        }
        event = svc.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=body).execute()
        eid   = event.get("id", "")
        elink = event.get("htmlLink", "")
        print(f"Event created: {eid} | {start_time_str} to {end_time_str}")
        return eid, elink, share
    except Exception as e:
        print(f"Calendar error: {e}")
        return None, str(e), share

def parse_date(s):
    today = datetime.date.today()
    s = str(s).lower().strip()
    if "today"    in s: return today.strftime("%Y-%m-%d")
    if "tomorrow" in s: return (today + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    for day, num in {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,"friday":4,"saturday":5,"sunday":6}.items():
        if day in s:
            diff = (num - today.weekday()) % 7 or 7
            return (today + datetime.timedelta(days=diff)).strftime("%Y-%m-%d")
    for fmt in ["%Y-%m-%d","%m/%d/%Y","%m/%d/%y","%B %d %Y","%B %d, %Y","%B %d","%b %d","%b %d %Y"]:
        try:
            p = datetime.datetime.strptime(s.strip(), fmt)
            if p.year == 1900: p = p.replace(year=today.year)
            return p.strftime("%Y-%m-%d")
        except: continue
    return (today + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

def fmt_dt_range(ds, start_ts, end_ts):
    try:
        start_dt = datetime.datetime.strptime(f"{ds} {start_ts}", "%Y-%m-%d %H:%M")
        end_dt = datetime.datetime.strptime(f"{ds} {end_ts}", "%Y-%m-%d %H:%M")
        date_str = start_dt.strftime("%A, %B %d, %Y")
        start_str = start_dt.strftime("%I:%M %p").lstrip("0")
        end_str = end_dt.strftime("%I:%M %p").lstrip("0")
        return f"{date_str} from {start_str} to {end_str}"
    except:
        return f"{ds} from {start_ts} to {end_ts}"

def fmt_date(ds):
    try: return datetime.datetime.strptime(ds, "%Y-%m-%d").strftime("%A, %B %d, %Y")
    except: return ds

def fmt_time(ts):
    try: return datetime.datetime.strptime(ts, "%H:%M").strftime("%I:%M %p").lstrip("0")
    except: return ts

def fmt_time_range(start_ts, end_ts):
    try:
        start = datetime.datetime.strptime(start_ts, "%H:%M").strftime("%I:%M %p").lstrip("0")
        end = datetime.datetime.strptime(end_ts, "%H:%M").strftime("%I:%M %p").lstrip("0")
        return f"{start} to {end}"
    except:
        return f"{start_ts} to {end_ts}"

def extract_json(text):
    m = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        try: return json.loads(m.group(1))
        except: pass
    return None

def clean_text(text):
    return re.sub(r'```json.*?```', '', text, flags=re.DOTALL).strip()

def demo_chat(messages, user_input):
    step = len([m for m in messages if m["role"] == "assistant"])
    um   = [m["content"] for m in messages if m["role"] == "user"] + [user_input]
    if step == 0: return "Hi! I'm Calendrix AI (demo mode). What's your name?"
    if step == 1: return f"Great, {user_input.strip()}! What date works for your meeting?"
    if step == 2: return "Perfect! What time? (e.g., 4 PM to 6 PM or 4:00-6:00)"
    if step == 3: return "What should we call this meeting? (or say 'skip')"
    
    name  = um[0] if um else "Guest"
    date  = parse_date(um[1]) if len(um) > 1 else parse_date("tomorrow")
    start_time, end_time = parse_time_range_strict(um[2]) if len(um) > 2 else ("10:00", "11:00")
    title = user_input if user_input.lower() not in ["skip","no","none",""] else f"Meeting with {name}"
    
    return (f"Perfect! Just to confirm: **{title}** for **{name}** on **{fmt_date(date)}** from "
            f"**{fmt_time(start_time)}** to **{fmt_time(end_time)}**. Shall I create this event?\n\n"
            f'```json\n{{"name":"{name}","date":"{date}","start_time":"{start_time}","end_time":"{end_time}","title":"{title}","confirmed":false}}\n```')

@app.route("/")
def index(): return render_template("index.html")

@app.route("/api/status")
def api_status():
    return jsonify({
        "openai":          bool(OPENAI_API_KEY) and OPENAI_AVAILABLE,
        "google_calendar": bool(GOOGLE_SERVICE_ACCOUNT_JSON) and GOOGLE_AVAILABLE,
        "demo_mode":       not bool(OPENAI_API_KEY),
        "calendar_id":     GOOGLE_CALENDAR_ID,
    })

@app.route("/api/start", methods=["POST"])
def start():
    g = "Hello! I'm Calendrix AI, your smart scheduling assistant. Let's get your meeting booked! What's your name?"
    session["messages"]     = [{"role": "assistant", "content": g}]
    session["booking_data"] = {}
    return jsonify({"message": g})

@app.route("/api/chat", methods=["POST"])
def chat():
    data   = request.get_json()
    uinput = (data.get("message") or "").strip()
    if not uinput: return jsonify({"error": "Empty"}), 400
    msgs  = session.get("messages", [])
    reply = chat_gpt(msgs, uinput)
    msgs.append({"role": "user",      "content": uinput})
    msgs.append({"role": "assistant", "content": reply})
    session["messages"] = msgs
    session.modified = True
    bd  = extract_json(reply)
    res = {"message": reply, "clean_message": clean_text(reply)}
    if bd:
        res["booking_data"]    = bd
        session["booking_data"] = bd
    return jsonify(res)

@app.route("/api/voice", methods=["POST"])
def voice():
    if "audio" not in request.files: return jsonify({"error": "No audio"}), 400
    af = request.files["audio"]
    ab = af.read()
    if len(ab) < 100: return jsonify({"error": "Recording too short"}), 400
    transcript = do_stt(ab, af.filename or "rec.webm")
    if not transcript: return jsonify({"error": "Could not transcribe. Check OpenAI key."}), 400
    msgs  = session.get("messages", [])
    reply = chat_gpt(msgs, transcript)
    msgs.append({"role": "user",      "content": transcript})
    msgs.append({"role": "assistant", "content": reply})
    session["messages"] = msgs
    session.modified = True
    bd  = extract_json(reply)
    res = {"transcript": transcript, "message": reply, "clean_message": clean_text(reply)}
    if bd:
        res["booking_data"]    = bd
        session["booking_data"] = bd
    return jsonify(res)

@app.route("/api/tts", methods=["POST"])
def tts():
    audio = do_tts(request.get_json().get("text", ""))
    if not audio: return jsonify({"error": "TTS unavailable"}), 503
    return Response(audio, mimetype="audio/mpeg")

@app.route("/api/confirm", methods=["POST"])
def confirm():
    data    = request.get_json()
    booking = data.get("booking") or session.get("booking_data") or {}
    if not booking: return jsonify({"error": "No booking data"}), 400

    name      = booking.get("name",  "Guest")
    date_str  = booking.get("date",  "")
    start_time_str = booking.get("start_time",  "10:00")
    end_time_str   = booking.get("end_time",    "11:00")
    title     = booking.get("title", f"Meeting with {name}")

    if not re.match(r"\d{4}-\d{2}-\d{2}", str(date_str)): 
        date_str = parse_date(str(date_str))
    
    if not re.match(r"\d{2}:\d{2}", str(start_time_str)): 
        start_time_str, end_time_str = parse_time_range_strict(f"{start_time_str} to {end_time_str}")
    if not re.match(r"\d{2}:\d{2}", str(end_time_str)): 
        end_time_str = strict_parse_time(str(end_time_str))

    event_id, event_link, share_link = make_event(name, date_str, start_time_str, end_time_str, title)
    if event_id is None:
        return jsonify({"error": f"Calendar error: {event_link}"}), 500

    conn = sqlite3.connect("scheduler.db")
    c    = conn.cursor()
    c.execute("INSERT INTO bookings (name,date,start_time,end_time,title,calendar_event_id,event_link) VALUES (?,?,?,?,?,?,?)",
              (name, date_str, start_time_str, end_time_str, title, event_id, event_link))
    conn.commit()
    conn.close()

    return jsonify({
        "success":    True,
        "event_id":   event_id,
        "event_link": event_link,
        "share_link": share_link,
        "summary": {
            "name":         name,
            "datetime":     fmt_dt_range(date_str, start_time_str, end_time_str),
            "display_date": fmt_date(date_str),
            "display_time": fmt_time_range(start_time_str, end_time_str),
            "title":        title,
        }
    })

@app.route("/api/bookings")
def get_bookings():
    conn = sqlite3.connect("scheduler.db")
    c    = conn.cursor()
    c.execute("SELECT id,name,date,start_time,end_time,title,calendar_event_id,event_link,created_at FROM bookings ORDER BY created_at DESC LIMIT 20")
    rows = c.fetchall()
    conn.close()
    return jsonify([{"id":r[0],"name":r[1],"date":r[2],"start_time":r[3],"end_time":r[4],
                     "title":r[5],"event_id":r[6],"event_link":r[7],"created_at":r[8]} for r in rows])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Open: http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
