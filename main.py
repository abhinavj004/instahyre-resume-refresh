import logging
import os
import random
import sys
import time

from dotenv import load_dotenv
from helper import get_resume_payload
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============================================================
# LOAD ENV
# ============================================================

load_dotenv()

# ============================================================
# CONFIG
# ============================================================

EMAIL = os.getenv("INSTAHYRE_EMAIL")
PASSWORD = os.getenv("INSTAHYRE_PASSWORD")
RESUME_FILE = "resume.pdf"

LOGIN_URL = "https://www.instahyre.com/api/v1/users/user_login"
PROFILE_URL = "https://www.instahyre.com/api/v1/candidate_misc/profile/candidate/157730"
LOGIN_PAGE_URL = "https://www.instahyre.com/login/"
LOGOUT_URL = "https://www.instahyre.com/logout/"

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

logger = logging.getLogger(__name__)

# ============================================================
# JITTER / SCHEDULE RANDOMIZATION
# ============================================================


def apply_jitter(min_seconds: int = 60, max_seconds: int = 900) -> int:
    """Applies a random delay between min_seconds and max_seconds in CI/GitHub Actions."""
    is_ci = os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("CI") == "true"

    if not is_ci:
        logger.info(
            "Local environment detected: Skipping schedule jitter for fast testing."
        )
        return 0

    delay = random.randint(min_seconds, max_seconds)
    mins, secs = divmod(delay, 60)
    logger.info(
        f"CI trigger detected. Applying random jitter: waiting for {mins}m {secs}s..."
    )
    time.sleep(delay)
    return delay


# ============================================================
# SESSION
# ============================================================


def create_session():
    session = requests.Session()

    retry_strategy = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PUT"],
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)

    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


# ============================================================
# LOGIN
# ============================================================


def login(session):
    logger.info("Fetching login page")

    session.get(LOGIN_PAGE_URL, timeout=30)

    csrf = session.cookies.get("csrftoken")

    logger.info("Logging into Instahyre")

    response = session.post(
        LOGIN_URL,
        json={"email": EMAIL, "password": PASSWORD},
        headers={
            "X-CSRFToken": csrf if csrf else "",
            "Referer": LOGIN_PAGE_URL,
            "Origin": "https://www.instahyre.com",
        },
        timeout=30,
    )

    response.raise_for_status()

    session_id = session.cookies.get("sessionid")

    if not session_id:
        raise Exception("Login failed. sessionid cookie not found")

    logger.info("Login successful")


# ============================================================
# PROFILE
# ============================================================


def get_profile(session):
    logger.info("Fetching profile")

    response = session.get(PROFILE_URL, timeout=30)

    response.raise_for_status()

    profile = response.json()

    logger.info(f"Profile loaded for {profile['user']['full_name']}")

    return profile


# ============================================================
# RESUME REFRESH
# ============================================================


def refresh_resume(session, profile):
    candidate_id = profile["id"]
    resume_id = profile["resume"]["id"]

    logger.info(
        f"Refreshing resume (Candidate={candidate_id}, Resume={resume_id})"
    )

    payload = get_resume_payload(
        pdf_path=RESUME_FILE,
        candidate_id=candidate_id,
        resume_id=resume_id,
        filename=os.path.basename(RESUME_FILE),
    )

    upload_url = f"https://www.instahyre.com/api/v1/candidate_misc/profile/resume/{resume_id}"

    response = session.put(
        upload_url,
        json=payload,
        headers={
            "X-CSRFToken": session.cookies.get("csrftoken"),
            "Origin": "https://www.instahyre.com",
            "Referer": "https://www.instahyre.com/candidate/profile/",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
        },
        timeout=120,
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("is_fresh"):
        raise Exception("Resume refresh failed. is_fresh=False")

    logger.info(
        f"Resume refreshed successfully at {result.get('uploaded_on')}"
    )

    return result


def refresh_jsp(session, profile):
    jsp = profile["jsp"]
    jsp_id = jsp["id"]

    logger.info(f"Refreshing JSP/Profile (JSP={jsp_id})")

    response = session.put(
        f"https://www.instahyre.com/api/v1/candidate_misc/profile/candidate_jsp/{jsp_id}",
        json=jsp,
        headers={
            "X-CSRFToken": session.cookies.get("csrftoken"),
            "Origin": "https://www.instahyre.com",
            "Referer": "https://www.instahyre.com/candidate/profile/",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
        },
        timeout=60,
    )

    response.raise_for_status()

    logger.info("JSP/Profile refresh completed")

    return response.json()


# ============================================================
# LOGOUT
# ============================================================


def logout(session):
    try:
        logger.info("Logging out")

        response = session.get(
            LOGOUT_URL,
            headers={
                "Referer": "https://www.instahyre.com/candidate/profile/",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/136.0.0.0 Safari/537.36"
                ),
            },
            timeout=30,
            allow_redirects=False,
        )

        if response.status_code in [200, 302]:
            logger.info(f"Logout successful (Status={response.status_code})")

        elif response.status_code == 403:
            logger.warning("Logout returned 403. Ignoring.")

        else:
            logger.warning(
                f"Unexpected logout status: {response.status_code}"
            )

    except Exception as e:
        logger.warning(f"Logout failed: {e}")


def send_telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.warning("Telegram not configured. Skipping notification.")
        return

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=20,
        )

        response.raise_for_status()

    except Exception as e:
        logger.warning(f"Telegram notification failed: {e}")


# ============================================================
# MAIN
# ============================================================


def main():
    if not EMAIL:
        raise Exception("INSTAHYRE_EMAIL environment variable not set")

    if not PASSWORD:
        raise Exception("INSTAHYRE_PASSWORD environment variable not set")

    if not os.path.exists(RESUME_FILE):
        raise FileNotFoundError(f"Resume file not found: {RESUME_FILE}")

    # 1. Apply Jitter Delay (1 to 15 mins) if running on GitHub Actions
    jitter_applied = apply_jitter(min_seconds=60, max_seconds=900)
    exec_start = time.time()

    session = create_session()

    try:
        login(session)

        profile = get_profile(session)

        old_uploaded_on = profile["resume"]["uploaded_on"]
        logger.info(f"Current resume timestamp: {old_uploaded_on}")

        result = refresh_resume(session, profile)

        profile_after_resume = get_profile(session)

        old_profile_update_ts = None
        updates = profile_after_resume.get("profile_field_updates", [])
        if updates:
            old_profile_update_ts = updates[0].get("last_modified_at")

        refresh_jsp(session, profile_after_resume)

        updated_profile = get_profile(session)

        new_uploaded_on = updated_profile["resume"]["uploaded_on"]
        logger.info(f"Updated resume timestamp: {new_uploaded_on}")

        new_profile_update_ts = None
        updates = updated_profile.get("profile_field_updates", [])
        if updates:
            new_profile_update_ts = updates[0].get("last_modified_at")

        if old_profile_update_ts == new_profile_update_ts:
            logger.warning("JSP refresh did not change profile timestamp")
        else:
            logger.info("JSP refresh verified successfully")

        if old_uploaded_on == new_uploaded_on:
            raise Exception("Resume upload succeeded but timestamp did not change")

        logger.info("Resume refresh verified successfully")

        # Format execution metrics
        exec_duration = round(time.time() - exec_start, 2)
        j_mins, j_secs = divmod(jitter_applied, 60)

        jitter_str = f"{j_mins}m {j_secs}s" if jitter_applied > 0 else "None (Local)"

        send_telegram(
            f"✅ Instahyre refresh successful\n\n"
            f"⏱ Jitter Delay: {jitter_str}\n"
            f"⚡ Execution: {exec_duration}s\n\n"
            f"Resume:\n{new_uploaded_on}\n\n"
            f"Profile:\n{new_profile_update_ts}"
        )

    finally:
        logout(session)
        session.close()

    logger.info("Job completed successfully")


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)

    except Exception as e:
        logger.exception(f"Job failed: {e}")

        try:
            send_telegram(f"❌ Instahyre refresh failed\n\nReason:\n{str(e)}")
        except Exception:
            pass

        sys.exit(1)
