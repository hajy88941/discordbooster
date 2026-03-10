import base64
import json
import random
import re
from typing import Dict, Optional, Tuple
_CHROME_VERSIONS = [
    "120.0.6099.130", "120.0.6099.199", "121.0.6167.85", "121.0.6167.160",
    "122.0.6261.57", "122.0.6261.112", "123.0.6312.58", "123.0.6312.86",
    "124.0.6367.60", "124.0.6367.91", "125.0.6422.76", "125.0.6422.112",
]
_WIN_NT_VERSIONS = ["10.0", "10.0", "10.0", "10.0", "11.0"]
_SYSTEM_LOCALES = [
    "en-US", "en-GB", "de-DE", "fr-FR", "es-ES", "pt-BR", "ru-RU",
    "pl-PL", "tr-TR", "it-IT", "nl-NL", "ja-JP", "ko-KR", "zh-CN",
]
_CLIENT_BUILD_NUMBERS = [
    254238, 254541, 255101, 255445, 256035, 256542, 257201,
    257856, 258301, 258912, 259400, 259877, 260334, 260812, 261200,
]
_RELEASE_CHANNELS = ["stable", "stable", "stable", "canary", "ptb"]
def generate_user_agent() -> str:
    chrome = random.choice(_CHROME_VERSIONS)
    nt = random.choice(_WIN_NT_VERSIONS)
    return (
        f"Mozilla/5.0 (Windows NT {nt}; Win64; x64) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome} Safari/537.36"
    )
def generate_super_properties(user_agent: str) -> str:
    chrome_match = re.search(r"Chrome/([\d.]+)", user_agent)
    chrome_ver = chrome_match.group(1) if chrome_match else "124.0.6367.91"
    nt_match = re.search(r"Windows NT ([\d.]+)", user_agent)
    nt_ver = nt_match.group(1) if nt_match else "10.0"
    os_display = "10" if nt_ver == "10.0" else "11"
    props = {
        "os": "Windows", "browser": "Chrome", "device": "",
        "system_locale": random.choice(_SYSTEM_LOCALES),
        "browser_user_agent": user_agent, "browser_version": chrome_ver,
        "os_version": os_display, "referrer": "", "referring_domain": "",
        "referrer_current": "", "referring_domain_current": "",
        "release_channel": random.choice(_RELEASE_CHANNELS),
        "client_build_number": random.choice(_CLIENT_BUILD_NUMBERS),
        "client_event_source": None,
    }
    return base64.b64encode(json.dumps(props, separators=(",", ":")).encode()).decode()
def generate_fingerprint() -> Tuple[str, str]:
    ua = generate_user_agent()
    sp = generate_super_properties(ua)
    return ua, sp
def build_headers(
    token: str, user_agent: str, super_properties: str, captcha_key: Optional[str] = None
) -> Dict[str, str]:
    major_match = re.search(r"Chrome/(\d+)", user_agent)
    major = major_match.group(1) if major_match else "124"
    headers: Dict[str, str] = {
        "Authorization": token,
        "User-Agent": user_agent,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": "https://discord.com",
        "Referer": "https://discord.com/channels/@me",
        "Sec-Ch-Ua": f'"Chromium";v="{major}", "Google Chrome";v="{major}", "Not_A Brand";v="8"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "X-Super-Properties": super_properties,
        "X-Discord-Locale": "en-US",
        "X-Discord-Timezone": "America/New_York",
    }
    if captcha_key:
        headers["X-Captcha-Key"] = captcha_key
    return headers
