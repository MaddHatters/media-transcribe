"""Patreon content source — auth, search, navigation with stealth."""
from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import TYPE_CHECKING

from src.config import CRED_TARGET
from src.sources.base import Post

if TYPE_CHECKING:
    from src.cdp import CDPClient

log = logging.getLogger(__name__)

SCROLL_PX_MIN = 600
SCROLL_PX_MAX = 1000
SCROLL_DELAY_MIN = 1.5
SCROLL_DELAY_MAX = 5.0
READING_PAUSE_CHANCE = 0.20
READING_PAUSE_MIN = 5.0
READING_PAUSE_MAX = 12.0
MOUSE_MOVE_CHANCE = 0.65


class PatreonSource:
    name = "patreon"

    def __init__(self, cred_target: str = CRED_TARGET):
        self._cred_target = cred_target

    async def authenticate(self, cdp: CDPClient) -> bool:
        await cdp.navigate("https://www.patreon.com/home", wait=5.0)

        login_detected = await cdp.js(
            "!!document.querySelector("
            "'input[name=\"email\"], "
            "form[action*=\"login\"], "
            "input[type=\"email\"]')"
        )

        if not login_detected:
            log.info("Patreon session is valid")
            await cdp.navigate("about:blank", wait=0.0)
            return True

        log.info("Login form detected — attempting auto-login")
        from src.capture.credentials import read_credential
        creds = read_credential(self._cred_target)
        if not creds:
            log.error("No credentials for target=%s", self._cred_target)
            return False

        email, password = creds

        await cdp.js(f"""(() => {{
            const el = document.querySelector('input[name="email"], input[type="email"]');
            if (el) {{
                el.focus();
                el.value = {json.dumps(email)};
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
            }}
        }})()""")
        await asyncio.sleep(1)

        await cdp.js("""(() => {
            const btns = [...document.querySelectorAll('button')];
            const next = btns.find(b => /continue|next|log\\s*in|sign\\s*in/i.test(b.textContent));
            if (next) next.click();
        })()""")
        await asyncio.sleep(3)

        await cdp.js(f"""(() => {{
            const el = document.querySelector('input[type="password"]');
            if (el) {{
                el.focus();
                el.value = {json.dumps(password)};
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
            }}
        }})()""")
        await asyncio.sleep(1)

        await cdp.js("""(() => {
            const btns = [...document.querySelectorAll('button')];
            const submit = btns.find(b => /log\\s*in|sign\\s*in|submit|continue/i.test(b.textContent));
            if (submit) submit.click();
        })()""")
        await asyncio.sleep(5)

        still_login = await cdp.js(
            "!!document.querySelector("
            "'input[name=\"email\"], form[action*=\"login\"]')"
        )
        if still_login:
            log.error("Login failed (form still present)")
            return False

        log.info("Login succeeded")
        await cdp.navigate("about:blank", wait=0.0)
        return True

    async def get_posts(self, cdp: CDPClient, query: str | None = None) -> list[Post]:
        return []

    async def navigate_to(self, cdp: CDPClient, url: str) -> None:
        await cdp.navigate(url, wait=8.0)

        if random.random() < MOUSE_MOVE_CHANCE:
            await cdp.move_mouse(
                random.randint(400, 1200),
                random.randint(200, 700),
            )
            await asyncio.sleep(random.uniform(0.1, 0.4))
