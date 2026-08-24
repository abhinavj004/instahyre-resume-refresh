import logging
import os
import requests

logger = logging.getLogger(__name__)

LOGIN_URL = "https://login.naukri.com/v1/login"
RESUME_HEADLINE_URL = "https://www.naukri.com/gateway/v1/profile/resume-headline"


def refresh_naukri_headline(
    username: str, password: str, proxy_url: str = None
) -> dict:
    if not username or not password:
        raise ValueError("Naukri credentials not provided.")

    session = requests.Session()

    # Route traffic through proxy if provided (bypasses GitHub IP blocking)
    if proxy_url:
        logger.info("Routing Naukri requests via proxy...")
        session.proxies = {"http": proxy_url, "https": proxy_url}

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "clientid": "naukri",
        "appid": "109",
        "systemid": "naukri",
        "Accept": "application/json",
    })

    # 1. Login
    logger.info("Logging into Naukri...")
    login_res = session.post(
        LOGIN_URL,
        json={"username": username, "password": password},
        timeout=30,
    )
    login_res.raise_for_status()

    login_data = login_res.json()
    token = login_data.get("token") or login_data.get("accessToken")
    if token:
        session.headers.update({"Authorization": f"Bearer {token}"})

    # 2. Get current headline
    logger.info("Fetching current Naukri headline...")
    get_res = session.get(RESUME_HEADLINE_URL, timeout=30)
    get_res.raise_for_status()
    current_headline = (
        get_res.json().get("resumeHeadline", {}).get("text", "").strip()
    )

    if not current_headline:
        raise Exception("Failed to retrieve current resume headline.")

    # 3. Toggle trailing dot
    new_headline = (
        current_headline[:-1]
        if current_headline.endswith(".")
        else f"{current_headline}."
    )

    # 4. Save headline update
    logger.info("Submitting updated headline to Naukri...")
    update_res = session.put(
        RESUME_HEADLINE_URL,
        json={"resumeHeadline": new_headline},
        timeout=30,
    )
    update_res.raise_for_status()

    logger.info("Naukri profile headline updated successfully.")
    return {"old_headline": current_headline, "new_headline": new_headline}
