import sys
from pathlib import Path
import schedule
import time


ROOT_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(
    0,
    str(ROOT_DIR)
)

def run_bot():
    raise RuntimeError(
        "The legacy daily all-asset scheduler is disabled. Use "
        "runtime/live_runtime.py with per-instrument completed-bar orchestration."
    )


def main():
    schedule.every().day.at("07:00").do(run_bot)

    print("Garner Quant Scheduler Started")
    print("Waiting for 07:00...")

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
