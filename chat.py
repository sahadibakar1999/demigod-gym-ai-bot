"""Test the bot in your terminal — no WhatsApp needed.

Type a message and press Enter.
Send a meal photo:  /photo path/to/meal.jpg
Quit:               /quit
"""
import mimetypes
from app import handle

phone, name = "919999999999", "Demo User"
print("Demigod Gym bot — type a message (/photo <file>, /quit)\n")

while True:
    msg = input("You: ").strip()
    if not msg:
        continue
    if msg == "/quit":
        break
    if msg.startswith("/photo "):
        path = msg[7:].strip().strip('"')
        mime = mimetypes.guess_type(path)[0] or "image/jpeg"
        reply = handle(phone, name, image=(open(path, "rb").read(), mime, ""))
    else:
        reply = handle(phone, name, text=msg)
    print("\nBot:", reply, "\n")
