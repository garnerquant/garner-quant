from notifications.alert_notifier import notify_plain_message


def send_message(message):
    result = notify_plain_message(message, label="Daily Telegram report")

    if result.get("sent"):
        print("Telegram message sent.")
    elif result.get("skipped"):
        print("Telegram not configured.")
    else:
        print(f"Telegram send failed: {result.get('reason')}")

    return result
