import logging
import os
import random
import sys
import time
from datetime import datetime
from http.cookies import SimpleCookie

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

NAUKRI_COOKIES = os.getenv("NAUKRI_COOKIES")
NAUKRI_PROXY_URL = os.getenv("NAUKRI_PROXY_URL")

NAUKRI_PROFILE_GET_URL = "https://www.naukri.com/cloudgateway-aurus/aurus-jobseeker-profile-wrapper/v0/jobseeker/users/self/get/fullprofiles"
NAUKRI_PROFILE_UPDATE_URL = "https://www.naukri.com/cloudgateway-aurus/aurus-jobseeker-profile-wrapper/v0/jobseeker/users/self/update/fullprofiles"

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
# TELEGRAM NOTIFIER
# ============================================================


def send_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured. Skipping notification.")
        return

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
            },
            timeout=20,
        )
        response.raise_for_status()
    except Exception as e:
        logger.warning(f"Telegram notification failed: {e}")


# ============================================================
# JITTER / SCHEDULE RANDOMIZATION
# ============================================================


def apply_jitter(min_seconds: int = 60, max_seconds: int = 900) -> int:
    is_ci = os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("CI") == "true"
    skip = os.getenv("SKIP_JITTER", "false").lower() == "true"

    if not is_ci or skip:
        logger.info("Jitter bypass active: Running immediately.")
        return 0

    delay = random.randint(min_seconds, max_seconds)
    mins, secs = divmod(delay, 60)
    logger.info(f"Applying random jitter: waiting for {mins}m {secs}s...")
    time.sleep(delay)
    return delay


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

    if not session.cookies.get("sessionid"):
        raise Exception("Instahyre login failed: sessionid cookie missing")
    logger.info("[Instahyre] Login successful")


def get_instahyre_profile(session: requests.Session) -> dict:
    response = session.get(INSTAHYRE_PROFILE_URL, timeout=30)
    response.raise_for_status()
    return response.json()


def refresh_instahyre_resume(session: requests.Session, profile: dict) -> dict:
    candidate_id = profile["id"]
    resume_id = profile["resume"]["id"]

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

    return result


def refresh_instahyre_jsp(session: requests.Session, profile: dict) -> dict:
    jsp = profile["jsp"]
    jsp_id = jsp["id"]

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
    return response.json()


def logout_instahyre(session: requests.Session) -> None:
    try:
        session.get(
            INSTAHYRE_LOGOUT_URL,
            headers={"Referer": "https://www.instahyre.com/candidate/profile/"},
            timeout=30,
            allow_redirects=False,
        )
    except Exception as e:
        logger.warning(f"[Instahyre] Logout failed: {e}")


def run_instahyre() -> dict:
    if not INSTAHYRE_EMAIL or not INSTAHYRE_PASSWORD:
        raise Exception("Missing Instahyre credentials.")
    if not os.path.exists(RESUME_FILE):
        raise FileNotFoundError(f"Resume file not found: {RESUME_FILE}")

    session = create_instahyre_session()
    try:
        login_instahyre(session)
        profile = get_instahyre_profile(session)

        old_uploaded_on = profile["resume"]["uploaded_on"]
        refresh_instahyre_resume(session, profile)

        profile_after_resume = get_instahyre_profile(session)
        old_profile_ts = (
            profile_after_resume.get("profile_field_updates", [{}])[0].get(
                "last_modified_at"
            )
            if profile_after_resume.get("profile_field_updates")
            else None
        )

        refresh_instahyre_jsp(session, profile_after_resume)

        updated_profile = get_instahyre_profile(session)
        new_uploaded_on = updated_profile["resume"]["uploaded_on"]
        new_profile_ts = (
            updated_profile.get("profile_field_updates", [{}])[0].get(
                "last_modified_at"
            )
            if updated_profile.get("profile_field_updates")
            else None
        )

        return {
            "old_resume": old_uploaded_on,
            "new_resume": new_uploaded_on,
            "old_profile": old_profile_ts,
            "new_profile": new_profile_ts,
        }

    finally:
        logout_instahyre(session)
        session.close()


# ============================================================
# NAUKRI ENGINE (FULL SESSION COOKIES)
# ============================================================


def run_naukri() -> dict:
    if not NAUKRI_COOKIES:
        raise Exception("NAUKRI_COOKIES environment variable not set")

    session = requests.Session()

    if NAUKRI_PROXY_URL:
        logger.info("[Naukri] Using configured proxy for request routing")
        session.proxies = {"http": NAUKRI_PROXY_URL, "https": NAUKRI_PROXY_URL}

    # Parse and set all session cookies
    cookie_parser = SimpleCookie()
    cookie_parser.load(NAUKRI_COOKIES)
    nauk_at_token = None

    for key, morsel in cookie_parser.items():
        session.cookies.set(key, morsel.value, domain=".naukri.com")
        if key == "nauk_at":
            nauk_at_token = morsel.value

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
        ),
        "clientid": "d3skt0p",
        "appid": "1950",
        "systemid": "Naukri",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://www.naukri.com",
        "Referer": "https://www.naukri.com/mnjuser/profile?id=&altresid",
    })

    if nauk_at_token:
        session.headers.update({"Authorization": f"Bearer {nauk_at_token}"})

    # 1. Fetch current profile state
    logger.info("[Naukri] Fetching current profile details...")
    profile_res = session.post(
        NAUKRI_PROFILE_GET_URL, json={"fieldMasks": []}, timeout=30
    )
    profile_res.raise_for_status()
    profile_json = profile_res.json()

    profile_items = profile_json.get("data", {}).get("profile", [])
    if not profile_items:
        raise Exception("Failed to locate profile item in Naukri profile response")

    profile_obj = profile_items[0]
    profile_id = profile_obj.get("profileId")
    current_summary = profile_obj.get("summary", "").strip()
    old_mod_time = profile_obj.get("lastModTime")

    if not current_summary or not profile_id:
        raise Exception("Could not find profileId or summary to refresh")

    # 2. Toggle trailing period on summary
    new_summary = (
        current_summary[:-1]
        if current_summary.endswith(".")
        else f"{current_summary}."
    )

    # 3. Submit updated summary
    logger.info("[Naukri] Submitting summary mutation to refresh timestamp...")
    update_payload = {
        "fieldMasks": [],
        "data": {"profile": {"summary": new_summary}, "profileId": profile_id},
    }

    update_res = session.post(
        NAUKRI_PROFILE_UPDATE_URL, json=update_payload, timeout=30
    )
    update_res.raise_for_status()

    # 4. Fetch updated profile to verify timestamp change
    verify_res = session.post(
        NAUKRI_PROFILE_GET_URL, json={"fieldMasks": []}, timeout=30
    )
    verify_res.raise_for_status()
    new_profile_obj = verify_res.json().get("data", {}).get("profile", [])[0]
    new_mod_time = new_profile_obj.get("lastModTime")
    new_mod_ago = new_profile_obj.get("lastModAgo")

    return {
        "old_time": old_mod_time,
        "new_time": new_mod_time,
        "badge": new_mod_ago,
    }


# ============================================================
# MAIN ORCHESTRATION & TELEGRAM REPORTING
# ============================================================


def main():
    jitter_applied = apply_jitter(min_seconds=1, max_seconds=2)
    exec_start = time.time()

    reports = []
    has_failure = False

    # 1. Execute Instahyre
    try:
        instahyre_data = run_instahyre()
        reports.append(
            f"🟢 *Instahyre: Success*\n"
            f"  • *Resume:* `{instahyre_data['new_resume']}`\n"
            f"  • *Profile:* `{instahyre_data['new_profile']}`"
        )
    except Exception as e:
        logger.exception(f"Instahyre refresh failed: {e}")
        reports.append(f"🔴 *Instahyre: Failed*\n  • *Reason:* `{str(e)}`")
        has_failure = True

    # 2. Execute Naukri
    try:
        naukri_data = run_naukri()
        reports.append(
            f"🟢 *Naukri: Success*\n"
            f"  • *Updated:* `{naukri_data['new_time']}`\n"
            f"  • *Recruiter Badge:* `{naukri_data['badge']}` (Active)"
        )
    except Exception as e:
        logger.exception(f"Naukri refresh failed: {e}")
        reports.append(f"🔴 *Naukri: Failed*\n  • *Reason:* `{str(e)}`")
        has_failure = True

    # 3. Execution Metrics & Consolidated Alert
    exec_duration = round(time.time() - exec_start, 2)
    j_mins, j_secs = divmod(jitter_applied, 60)
    jitter_str = (
        f"{j_mins}m {j_secs}s" if jitter_applied > 0 else "None (Bypassed/Local)"
    )

    overall_header = (
        "⚠️ *Profile Refresh Finished with Issues*"
        if has_failure
        else "🚀 *Daily Profile Refresh Completed*"
    )
    current_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    msg_lines = [
        overall_header,
        "",
        f"⏱ *Jitter Delay:* {jitter_str}",
        f"⚡ *Execution Time:* {exec_duration}s",
        f"🕒 *Run Timestamp:* `{current_ts}`",
        "",
        "---",
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
                f"❌ *Fatal Orchestration Crash*\n\nReason: `{str(e)}`"
            )
        except Exception:
            pass
        sys.exit(1)
