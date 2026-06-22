import requests


BOT_TOKEN = "8855883281:AAFGBScxjDRfHXUDMOEf7j4HRxhZpa-yxtQ"
CHAT_ID = "5467581740"


def send_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }

    requests.post(url, data=payload)