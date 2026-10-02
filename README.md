# Demigod Gym AI Bot (demo)

## What it does
- Sales chat: fees, timings, classes, books free trial → saved to `trials.csv`
- Workout + Indian diet plan for the member's goal
- Meal photo → calories & protein estimate
- Injury / medical → hands over to a human coach (owner gets an alert)

## Files
- `app.py` — the bot (WhatsApp webhook + AI)
- `chat.py` — test in terminal
- `gym_info.md` — gym prices, timings, schedule (edit this, not the code)

## Pitch demo (browser)
```
bash demo.sh
```
Opens http://localhost:8000 — customer chat on the left, owner view on the right.
Press **Reset demo** before each pitch.

## Step 1 — Test in terminal (5 min)
```
pip install -r requirements.txt
copy .env.example .env        (Mac/Linux: cp)
# put your GROQ_API_KEY in .env  (free at console.groq.com)
python chat.py
```
Try:
- `fees kitni hai?`
- `I want to lose 5 kg, veg, can come 4 days a week. Give me a plan`
- `Book a trial for Rahul, Monday 7 PM, boxing`
- `I have knee pain, what should I do?`
- `/photo meal.jpg`

## Step 2 — Real WhatsApp
1. Meta Developers → create app → add WhatsApp → copy token + phone number ID into `.env`
2. Run: `uvicorn app:app --port 8000`
3. Expose it: `ngrok http 8000`
4. In Meta → WhatsApp → Configuration → Webhook:
   - URL: `https://<ngrok-url>/webhook`
   - Verify token: same as `VERIFY_TOKEN`
   - Subscribe to `messages`
5. Message the test number from your phone.

## Before showing the client
- Confirm the lines marked CONFIRM in `gym_info.md` (timings, phone, timetable)
- Chat memory is in RAM (resets on restart) — fine for a demo
