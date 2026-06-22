import requests


BOT_TOKEN = "PASTE_YOUR_TOKEN_HERE"
CHAT_ID = "5467581740"


def send_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }

    requests.post(url, data=payload)