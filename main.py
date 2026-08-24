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

# ============================================================
# LOAD ENV
# ============================================================

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
# CONFIG - NAUKRI
# ============================================================

NAUKRI_USERNAME = os.getenv("NAUKRI_USERNAME")
NAUKRI_PASSWORD = os.getenv("NAUKRI_PASSWORD")
NAUKRI_PROXY_URL = os.getenv("NAUKRI_PROXY_URL")

NAUKRI_LOGIN_URL = "https://login.naukri.com/v1/login"
NAUKRI_PROFILE_URL = "https://www.naukri.com/gateway/v1/profile"
NAUKRI_HEADLINE_URL = "https://www.naukri.com/gateway/v1/profile/resume-headline"

# ============================================================
# CONFIG - TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

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
    """Applies a random delay in CI/GitHub Actions to prevent static time footprints."""
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
# TELEGRAM NOTIFIER
# ============================================================


def send_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured. Skipping notification.")
        return

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=20,
        )
        response.raise_for_status()
    except Exception as e:
        logger.warning(f"Telegram notification failed: {e}")


# ============================================================
# INSTAHYRE ENGINE
# ============================================================


def create_instahyre_session() -> requests.Session:
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


def login_instahyre(session: requests.Session) -> None:
    logger.info("[Instahyre] Fetching login page")
    session.get(INSTAHYRE_LOGIN_PAGE_URL, timeout=30)
    csrf = session.cookies.get("csrftoken")

    logger.info("[Instahyre] Logging in...")
    response = session.post(
        INSTAHYRE_LOGIN_URL,
        json={"email": INSTAHYRE_EMAIL, "password": INSTAHYRE_PASSWORD},
        headers={
            "X-CSRFToken": csrf if csrf else "",
            "Referer": INSTAHYRE_LOGIN_PAGE_URL,
            "Origin": "https://www.instahyre.com",
        },
        timeout=30,
    )
    response.raise_for_status()

    session_id = session.cookies.get("sessionid")
    if not session_id:
        raise Exception("Instahyre login failed: sessionid cookie not found")
    logger.info("[Instahyre] Login successful")


def get_instahyre_profile(session: requests.Session) -> dict:
    logger.info("[Instahyre] Fetching profile")
    response = session.get(INSTAHYRE_PROFILE_URL, timeout=30)
    response.raise_for_status()
    profile = response.json()
    logger.info(
        f"[Instahyre] Profile loaded for {profile['user']['full_name']}"
    )
    return profile


def refresh_instahyre_resume(session: requests.Session, profile: dict) -> dict:
    candidate_id = profile["id"]
    resume_id = profile["resume"]["id"]

    logger.info(
        f"[Instahyre] Refreshing resume (Candidate={candidate_id}, Resume={resume_id})"
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
        raise Exception("Instahyre resume refresh failed: is_fresh=False")

    logger.info(
        f"[Instahyre] Resume refreshed successfully at {result.get('uploaded_on')}"
    )
    return result


def refresh_instahyre_jsp(session: requests.Session, profile: dict) -> dict:
    jsp = profile["jsp"]
    jsp_id = jsp["id"]

    logger.info(f"[Instahyre] Refreshing JSP/Profile (JSP={jsp_id})")
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
    logger.info("[Instahyre] JSP/Profile refresh completed")
    return response.json()


def logout_instahyre(session: requests.Session) -> None:
    try:
        logger.info("[Instahyre] Logging out...")
        response = session.get(
            INSTAHYRE_LOGOUT_URL,
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
            logger.info(
                f"[Instahyre] Logout successful (Status={response.status_code})"
            )
        elif response.status_code == 403:
            logger.warning("[Instahyre] Logout returned 403. Ignoring.")
        else:
            logger.warning(
                f"[Instahyre] Unexpected logout status: {response.status_code}"
            )
    except Exception as e:
        logger.warning(f"[Instahyre] Logout failed: {e}")


def run_instahyre() -> tuple[str, str]:
    if not INSTAHYRE_EMAIL:
        raise Exception("INSTAHYRE_EMAIL environment variable not set")
    if not INSTAHYRE_PASSWORD:
        raise Exception("INSTAHYRE_PASSWORD environment variable not set")
    if not os.path.exists(RESUME_FILE):
        raise FileNotFoundError(f"Resume file not found: {RESUME_FILE}")

    session = create_instahyre_session()
    try:
        login_instahyre(session)
        profile = get_instahyre_profile(session)

        old_uploaded_on = profile["resume"]["uploaded_on"]
        logger.info(f"[Instahyre] Current resume timestamp: {old_uploaded_on}")

        refresh_instahyre_resume(session, profile)

        profile_after_resume = get_instahyre_profile(session)
        old_profile_update_ts = None
        updates = profile_after_resume.get("profile_field_updates", [])
        if updates:
            old_profile_update_ts = updates[0].get("last_modified_at")

        refresh_instahyre_jsp(session, profile_after_resume)

        updated_profile = get_instahyre_profile(session)
        new_uploaded_on = updated_profile["resume"]["uploaded_on"]
        logger.info(f"[Instahyre] Updated resume timestamp: {new_uploaded_on}")

        new_profile_update_ts = None
        updates = updated_profile.get("profile_field_updates", [])
        if updates:
            new_profile_update_ts = updates[0].get("last_modified_at")

        if old_profile_update_ts == new_profile_update_ts:
            logger.warning(
                "[Instahyre] JSP refresh did not change profile timestamp"
            )
        else:
            logger.info("[Instahyre] JSP refresh verified successfully")

        if old_uploaded_on == new_uploaded_on:
            raise Exception(
                "Instahyre upload succeeded but timestamp did not change"
            )

        logger.info("[Instahyre] Refresh flow fully verified")
        return str(new_uploaded_on), str(new_profile_update_ts)

    finally:
        logout_instahyre(session)
        session.close()


# ============================================================
# NAUKRI ENGINE
# ============================================================


def run_naukri() -> str:
    if not NAUKRI_USERNAME or not NAUKRI_PASSWORD:
        raise Exception(
            "NAUKRI_USERNAME or NAUKRI_PASSWORD environment variable not set"
        )

    session = requests.Session()

    if NAUKRI_PROXY_URL:
        logger.info("[Naukri] Using configured proxy for request routing")
        session.proxies = {"http": NAUKRI_PROXY_URL, "https": NAUKRI_PROXY_URL}

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "clientid": "naukri",
        "appid": "109",
        "systemid": "naukri",
        "Accept": "application/json, text/plain, */*",
    })

    # 1. Login
    logger.info("[Naukri] Logging in...")
    login_res = session.post(
        NAUKRI_LOGIN_URL,
        json={"username": NAUKRI_USERNAME, "password": NAUKRI_PASSWORD},
        timeout=30,
    )
    login_res.raise_for_status()

    login_data = login_res.json()
    token = login_data.get("token") or login_data.get("accessToken")
    if token:
        session.headers.update({"Authorization": f"Bearer {token}"})
    logger.info("[Naukri] Authentication successful")

    # 2. Get headline
    logger.info("[Naukri] Fetching current resume headline...")
    get_res = session.get(NAUKRI_HEADLINE_URL, timeout=30)
    get_res.raise_for_status()
    current_headline = (
        get_res.json().get("resumeHeadline", {}).get("text", "").strip()
    )

    if not current_headline:
        raise Exception("Failed to retrieve current resume headline from Naukri")

    # 3. Toggle trailing dot
    new_headline = (
        current_headline[:-1]
        if current_headline.endswith(".")
        else f"{current_headline}."
    )

    # 4. Save headline update
    logger.info("[Naukri] Submitting updated headline...")
    update_res = session.put(
        NAUKRI_HEADLINE_URL,
        json={"resumeHeadline": new_headline},
        timeout=30,
    )
    update_res.raise_for_status()

    logger.info("[Naukri] Headline updated successfully")
    return new_headline


# ============================================================
# MAIN ORCHESTRATION
# ============================================================


def main():
    jitter_applied = apply_jitter(min_seconds=60, max_seconds=900)
    exec_start = time.time()

    reports = []
    has_failure = False

    # 1. Execute Instahyre
    try:
        instahyre_resume_ts, instahyre_profile_ts = run_instahyre()
        reports.append(
            f"🟢 *Instahyre: Success*\n"
            f"• Resume: {instahyre_resume_ts}\n"
            f"• Profile: {instahyre_profile_ts}"
        )
    except Exception as e:
        logger.exception(f"Instahyre refresh failed: {e}")
        reports.append(f"🔴 *Instahyre: Failed*\n• Reason: {str(e)}")
        has_failure = True

    # 2. Execute Naukri
    try:
        naukri_headline = run_naukri()
        reports.append("🟢 *Naukri: Success*\n• Status: Headline toggled")
    except Exception as e:
        logger.exception(f"Naukri refresh failed: {e}")
        reports.append(f"🔴 *Naukri: Failed*\n• Reason: {str(e)}")
        has_failure = True

    # 3. Execution Metrics & Consolidated Alert
    exec_duration = round(time.time() - exec_start, 2)
    j_mins, j_secs = divmod(jitter_applied, 60)
    jitter_str = (
        f"{j_mins}m {j_secs}s" if jitter_applied > 0 else "None (Local)"
    )

    overall_status = "⚠️ Daily Refresh Finished with Issues" if has_failure else "✅ Daily Profile Refresh Successful"
    msg_lines = [
        overall_status,
        "",
        f"⏱ *Jitter Delay:* {jitter_str}",
        f"⚡ *Execution:* {exec_duration}s",
        f"🕒 *Timestamp:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        *reports,
    ]

    send_telegram("\n".join(msg_lines))

    if has_failure:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Fatal orchestration error: {e}")
        try:
            send_telegram(
                f"❌ Profile Refresh Fatal Crash\n\nReason: {str(e)}"
            )
        except Exception:
            pass
        sys.exit(1)
