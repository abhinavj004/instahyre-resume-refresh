import logging
import os
import random
import sys
import time
from datetime import datetime
from dotenv import load_dotenv
from helper import get_resume_payload
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()

# ============================================================
# CONFIG - INSTAHYRE
# ============================================================

INSTAHYRE_EMAIL = os.getenv("INSTAHYRE_EMAIL")
INSTAHYRE_PASSWORD = os.getenv("INSTAHYRE_PASSWORD")
RESUME_FILE = "resume.pdf"

INSTAHYRE_LOGIN_URL = "https://www.instahyre.com/api/v1/users/user_login"
INSTAHYRE_PROFILE_URL = "https://www.instahyre.com/api/v1/candidate_misc/profile/candidate/157730"
INSTAHYRE_LOGIN_PAGE_URL = "https://www.instahyre.com/login/"
INSTAHYRE_LOGOUT_URL = "https://www.instahyre.com/logout/"

# ============================================================
# CONFIG - TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def send_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"},
            timeout=20,
        )
    except Exception as e:
        logger.warning(f"Telegram notification failed: {e}")

def apply_jitter(min_seconds: int = 60, max_seconds: int = 900) -> int:
    is_ci = os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("CI") == "true"
    skip = os.getenv("SKIP_JITTER", "false").lower() == "true"
    if not is_ci or skip:
        return 0
    delay = random.randint(min_seconds, max_seconds)
    time.sleep(delay)
    return delay

def run_instahyre() -> dict:
    if not INSTAHYRE_EMAIL or not INSTAHYRE_PASSWORD:
        raise Exception("Missing Instahyre credentials.")
    if not os.path.exists(RESUME_FILE):
        raise FileNotFoundError(f"Resume file not found: {RESUME_FILE}")

    session = requests.Session()
    retry_strategy = Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry_strategy))

    try:
        session.get(INSTAHYRE_LOGIN_PAGE_URL, timeout=30)
        csrf = session.cookies.get("csrftoken")

        login_res = session.post(
            INSTAHYRE_LOGIN_URL,
            json={"email": INSTAHYRE_EMAIL, "password": INSTAHYRE_PASSWORD},
            headers={"X-CSRFToken": csrf or "", "Referer": INSTAHYRE_LOGIN_PAGE_URL, "Origin": "https://www.instahyre.com"},
            timeout=30,
        )
        login_res.raise_for_status()

        profile = session.get(INSTAHYRE_PROFILE_URL, timeout=30).json()
        candidate_id = profile["id"]
        resume_id = profile["resume"]["id"]
        old_uploaded_on = profile["resume"]["uploaded_on"]

        # 1. Refresh Resume
        payload = get_resume_payload(
            pdf_path=RESUME_FILE,
            candidate_id=candidate_id,
            resume_id=resume_id,
            filename=os.path.basename(RESUME_FILE),
        )
        session.put(
            f"https://www.instahyre.com/api/v1/candidate_misc/profile/resume/{resume_id}",
            json=payload,
            headers={"X-CSRFToken": session.cookies.get("csrftoken"), "Origin": "https://www.instahyre.com", "Referer": "https://www.instahyre.com/candidate/profile/", "Content-Type": "application/json"},
            timeout=120,
        ).raise_for_status()

        # 2. Refresh JSP
        profile_after_resume = session.get(INSTAHYRE_PROFILE_URL, timeout=30).json()
        jsp = profile_after_resume["jsp"]
        session.put(
            f"https://www.instahyre.com/api/v1/candidate_misc/profile/candidate_jsp/{jsp['id']}",
            json=jsp,
            headers={"X-CSRFToken": session.cookies.get("csrftoken"), "Origin": "https://www.instahyre.com", "Referer": "https://www.instahyre.com/candidate/profile/", "Content-Type": "application/json;charset=UTF-8"},
            timeout=60,
        ).raise_for_status()

        updated_profile = session.get(INSTAHYRE_PROFILE_URL, timeout=30).json()
        new_uploaded_on = updated_profile["resume"]["uploaded_on"]
        new_profile_ts = updated_profile.get("profile_field_updates", [{}])[0].get("last_modified_at")

        return {"old_resume": old_uploaded_on, "new_resume": new_uploaded_on, "new_profile": new_profile_ts}
    finally:
        try:
            session.get(INSTAHYRE_LOGOUT_URL, timeout=30)
        except Exception:
            pass
        session.close()

def main():
    jitter = apply_jitter(min_seconds=60, max_seconds=900)
    start = time.time()
    try:
        data = run_instahyre()
        exec_time = round(time.time() - start, 2)
        msg = (
            "🚀 *Instahyre Daily Refresh Completed*\n\n"
            f"🟢 *Status:* Success\n"
            f"  • *Resume:* `{data['new_resume']}`\n"
            f"  • *Profile:* `{data['new_profile']}`\n\n"
            f"⚡ *Time:* {exec_time}s | 🕒 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        )
        send_telegram(msg)
    except Exception as e:
        logger.exception("Instahyre failure")
        send_telegram(f"🔴 *Instahyre Refresh Failed*\n\nReason: `{str(e)}`")
        sys.exit(1)

if __name__ == "__main__":
    main()
