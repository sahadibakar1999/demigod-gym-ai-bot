"""Demigod Gym - AI WhatsApp assistant (demo).

Does 5 things:
1. Sales chat: answers fees/timings/classes, books a free trial, saves every lead
2. Workout + diet plan for the member's goal
3. Meal photo -> calories & protein estimate
4. Injury/medical cases -> handed to a human coach
5. Daily run: renewal reminders + "we miss you" messages for members
"""
import os, re, csv, base64, datetime
import requests
from fastapi import FastAPI, Request, Response, Body
from fastapi.responses import FileResponse
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
WA_TOKEN = os.getenv("WA_TOKEN", "")
WA_PHONE_ID = os.getenv("WA_PHONE_ID", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "demigod123")
OWNER_PHONE = os.getenv("OWNER_PHONE", "")
TEXT_MODEL = os.getenv("TEXT_MODEL", "openai/gpt-oss-120b")
VISION_MODEL = os.getenv("VISION_MODEL", "qwen/qwen3.8-27b")

BASE = os.path.dirname(os.path.abspath(__file__))
TRIALS, LEADS, MEMBERS = (os.path.join(BASE, f) for f in ("trials.csv", "leads.csv", "members.csv"))
GYM_INFO = open(os.path.join(BASE, "gym_info.md"), encoding="utf-8").read()

SYSTEM = f"""You are the WhatsApp assistant of Demigod Gym. Today: {{today}}.

GYM INFO:
{GYM_INFO}

YOUR JOBS:
1. Answer questions about fees, timings, classes. Use ONLY the gym info above.
2. Book a FREE trial: collect name, day, time, goal. When you have all 4, confirm it
   and add this tag at the very end: [[TRIAL|name|day|time|goal]]
   Tell them the team will message to confirm the slot.
3. If asked for a workout or diet plan: first ask goal, level, days per week, veg/non-veg
   (only what's missing). Then give a simple weekly plan using Demigod's programs,
   and an Indian diet plan (roti, dal, paneer, eggs, chicken, curd...) with a protein target.
4. If the person mentions an injury, pain, pregnancy, heart/BP/sugar or any medical issue:
   do NOT give a plan. Say a Demigod coach will personally design it and contact them.
   Add at the very end: [[COACH|short reason]]

RULES:
- Reply in the same language they use (English / Hindi / Hinglish).
- Short WhatsApp-style messages. Max 1-2 emojis. Friendly, never pushy.
- WhatsApp formatting only: *bold* with single stars. No tables, no # headings, no **.
- Never invent prices, timings, class slots, offers or phone numbers not in the gym info.
- Veg means no eggs, meat or fish (unless they say they eat eggs).
"""

MEAL_PROMPT = """You are a sports nutritionist at Demigod Gym. Look at this meal photo (likely Indian food).
Reply in this short WhatsApp format:
🍽️ What I see: <items with rough portions>
🔥 Calories: ~<number> kcal
💪 Protein: ~<number> g
👉 Tip: <one simple tip to improve it for gym goals>
Say these are estimates."""

NUDGE_PROMPT = """Write one short WhatsApp message (under 80 words, max 1-2 emojis, Hinglish) from Demigod Gym.
Purpose: {purpose}
Member: {name}, plan: {plan}, goal: {goal}. {detail}
Warm and friendly, never pushy. Do not promise any discount or offer.
Write ONLY the message text."""

chats = {}   # phone -> list of messages (memory)
alerts = []  # owner alerts, newest last
_client = None


def llm():
    global _client
    if _client is None:
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


# ---------- AI ----------
def ask_ai(phone, text):
    history = chats.setdefault(phone, [])
    history.append({"role": "user", "content": text})
    system = SYSTEM.replace("{today}", datetime.date.today().strftime("%A, %d %B %Y"))
    reply = llm().chat.completions.create(
        model=TEXT_MODEL,
        messages=[{"role": "system", "content": system}] + history[-20:],
        temperature=0.6,
        max_tokens=2500,
    ).choices[0].message.content
    history.append({"role": "assistant", "content": reply})
    return reply


def analyze_meal(phone, image_bytes, mime="image/jpeg", caption=""):
    b64 = base64.b64encode(image_bytes).decode()
    reply = llm().chat.completions.create(
        model=VISION_MODEL,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": MEAL_PROMPT + ("\nUser note: " + caption if caption else "")},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ]}],
        max_tokens=1500,
    ).choices[0].message.content
    chats.setdefault(phone, []).append({"role": "assistant", "content": "[Meal analysis] " + reply})
    return reply


# ---------- CSV "sheets" ----------
def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def save_lead(phone, name, message, status):
    """One row per phone. Status only moves forward: chatting -> coach needed -> trial booked."""
    rank = ["chatting", "coach needed", "trial booked"]
    rows = read_csv(LEADS)
    row = next((r for r in rows if r["phone"] == phone), None)
    if row is None:
        row = {"phone": phone, "name": name, "status": "chatting"}
        rows.append(row)
    if rank.index(status) > rank.index(row["status"]):
        row["status"] = status
    row["last_message"] = (message or "")[:80]
    row["updated_at"] = datetime.datetime.now().isoformat(timespec="minutes")
    write_csv(LEADS, rows, ["phone", "name", "status", "last_message", "updated_at"])


# ---------- Actions from AI tags ----------
def process_tags(phone, name, reply):
    status = "chatting"
    for t in re.findall(r"\[\[TRIAL\|(.*?)\]\]", reply):
        parts = (t.split("|") + ["", "", "", ""])[:4]
        new_file = not os.path.exists(TRIALS)
        with open(TRIALS, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["booked_at", "phone", "name", "day", "time", "goal"])
            w.writerow([datetime.datetime.now().isoformat(timespec="minutes"), phone] + parts)
        notify_owner(f"✅ New trial booked\n{parts[0]} ({phone})\n{parts[1]} {parts[2]}\nGoal: {parts[3]}")
        status = "trial booked"

    for reason in re.findall(r"\[\[COACH\|(.*?)\]\]", reply):
        notify_owner(f"⚠️ Coach needed\n{name} ({phone})\nReason: {reason}")
        if status == "chatting":
            status = "coach needed"

    return re.sub(r"\s*\[\[(TRIAL|COACH)\|.*?\]\]", "", reply).strip(), status


def handle(phone, name="Guest", text=None, image=None):
    """Main brain. image = (bytes, mime, caption) or None. Returns reply text."""
    if image:
        save_lead(phone, name, "[meal photo]", "chatting")
        return analyze_meal(phone, *image)
    reply, status = process_tags(phone, name, ask_ai(phone, text or "Hi"))
    save_lead(phone, name, text, status)
    return reply


# ---------- Daily run: renewals + inactive members ----------
def sample_members():
    """Sample member list with dates relative to today, so the demo works on any day."""
    d = lambda n: (datetime.date.today() + datetime.timedelta(days=n)).isoformat()
    rows = [
        ("Aarav Sharma", "910000000001", "Warrior Monthly", d(3), d(-1), "muscle gain"),
        ("Priya Nair", "910000000002", "Initiate Quarterly", d(6), d(-2), "weight loss"),
        ("Rohit Verma", "910000000003", "DemiGod Annual", d(140), d(-12), "Hyrox race prep"),
        ("Sneha Kapoor", "910000000004", "Warrior Quarterly", d(40), d(-9), "general fitness"),
        ("Kabir Singh", "910000000005", "Initiate Monthly", d(20), d(-1), "boxing"),
    ]
    fields = ["name", "phone", "plan", "expiry_date", "last_visit", "goal"]
    write_csv(MEMBERS, [dict(zip(fields, r)) for r in rows], fields)


def daily_run():
    """Writes the messages. Demo: shows them only, does not send to members."""
    if not os.path.exists(MEMBERS):
        sample_members()
    today, out = datetime.date.today(), []
    for m in read_csv(MEMBERS):
        days_left = (datetime.date.fromisoformat(m["expiry_date"]) - today).days
        days_away = (today - datetime.date.fromisoformat(m["last_visit"])).days
        if -1 <= days_left < 8:
            kind, purpose = "Renewal reminder", "remind them to renew their membership"
            detail = f"Membership ends in {days_left} days ({m['expiry_date']})."
        elif days_away >= 7 and days_left > 0:
            kind, purpose = "We miss you", "bring back a member who stopped coming, without blaming them"
            detail = f"Last visit was {days_away} days ago. Add one quick tip for their goal."
        else:
            continue
        text = llm().chat.completions.create(
            model=TEXT_MODEL,
            messages=[{"role": "user", "content": NUDGE_PROMPT.format(
                purpose=purpose, name=m["name"], plan=m["plan"], goal=m["goal"], detail=detail)}],
            temperature=0.7,
            max_tokens=1200,
        ).choices[0].message.content.strip()
        out.append({"type": kind, "name": m["name"], "phone": m["phone"], "why": detail, "message": text})
    return out


# ---------- WhatsApp ----------
def send_wa(to, text):
    if not (WA_TOKEN and WA_PHONE_ID):
        return
    requests.post(
        f"https://graph.facebook.com/v18.0/{WA_PHONE_ID}/messages",
        headers={"Authorization": f"Bearer {WA_TOKEN}"},
        json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}},
        timeout=15,
    )


def notify_owner(text):
    print("[OWNER ALERT]", text)
    alerts.append({"at": datetime.datetime.now().strftime("%H:%M"), "text": text})
    if OWNER_PHONE:
        send_wa(OWNER_PHONE, text)


def download_media(media_id):
    h = {"Authorization": f"Bearer {WA_TOKEN}"}
    info = requests.get(f"https://graph.facebook.com/v18.0/{media_id}", headers=h, timeout=15).json()
    data = requests.get(info["url"], headers=h, timeout=30).content
    return data, info.get("mime_type", "image/jpeg")


app = FastAPI()


@app.get("/webhook")  # Meta verification
def verify(request: Request):
    q = request.query_params
    if q.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(q.get("hub.challenge", ""))
    return Response("forbidden", status_code=403)


@app.post("/webhook")  # incoming WhatsApp messages
async def webhook(request: Request):
    body = await request.json()
    try:
        value = body["entry"][0]["changes"][0]["value"]
        msg = value["messages"][0]  # no 'messages' = delivery/read receipt -> ignore
    except (KeyError, IndexError):
        return "ok"

    phone = msg["from"]
    name = value.get("contacts", [{}])[0].get("profile", {}).get("name", "Guest")

    try:
        if msg["type"] == "text":
            reply = handle(phone, name, text=msg["text"]["body"])
        elif msg["type"] == "image":
            data, mime = download_media(msg["image"]["id"])
            reply = handle(phone, name, image=(data, mime, msg["image"].get("caption", "")))
        else:
            reply = "Abhi main text aur photos samajh sakta hoon 🙂 Please type your question."
    except Exception as e:
        print("ERROR:", e)
        reply = "Sorry, thoda issue aa gaya. Our team will reply shortly."
        notify_owner(f"❌ Bot error for {phone}: {e}")

    send_wa(phone, reply)
    return "ok"


# ---------- Demo page (no WhatsApp needed) ----------
@app.get("/")
def demo_page():
    return FileResponse(os.path.join(BASE, "demo.html"))


@app.post("/chat")  # image = data URL from the browser, optional
def chat(b: dict = Body(...)):
    phone, name = b.get("phone", "test"), b.get("name", "Guest")
    try:
        if b.get("image"):
            head, data = b["image"].split(",", 1)
            mime = head[5:].split(";")[0] or "image/jpeg"
            return {"reply": handle(phone, name, image=(base64.b64decode(data), mime, b.get("message") or ""))}
        return {"reply": handle(phone, name, text=b.get("message"))}
    except Exception as e:
        print("ERROR:", e)
        notify_owner(f"❌ Bot error for {phone}: {e}")
        return {"reply": "Sorry, thoda issue aa gaya. Our team will reply shortly."}


@app.get("/owner")  # what the gym owner sees
def owner():
    return {"trials": read_csv(TRIALS), "leads": read_csv(LEADS), "alerts": alerts[::-1]}


@app.post("/daily")
def daily():
    return {"messages": daily_run()}


@app.post("/reset")  # clean slate before a pitch
def reset():
    chats.clear()
    alerts.clear()
    for p in (TRIALS, LEADS):
        if os.path.exists(p):
            os.remove(p)
    sample_members()
    return {"ok": True}
