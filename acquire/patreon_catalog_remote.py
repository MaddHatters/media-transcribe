#!/usr/bin/env python3
"""CDP-based Patreon content cataloger for the obs-machine.

Connects to Chrome via CDP (localhost:9222), navigates to a creator's posts
page, and slowly scrolls through all posts — like a human reading the feed —
extracting metadata into a structured JSON catalog.

Stealth: randomised scroll distance (600-1000 px), randomised delays
(1.5-5 s), occasional reading pauses, mouse wiggles, and small scroll-backs
to mimic a human browsing the feed.  Single session, no rapid reloads.

Deployed to:  C:\\Users\\Matt\\agent-control\\scripts\\patreon_catalog.py
Invoked by:   acquire/catalog_patreon.py on devbox-01 via SSH.

Usage (on the obs-machine directly):
  cd C:\\Users\\Matt\\agent-control
  uv run scripts\\patreon_catalog.py "https://www.patreon.com/cw/firedupwealth/posts"
  uv run scripts\\patreon_catalog.py "..." --known-urls state\\known_urls.json
  uv run scripts\\patreon_catalog.py "..." --list-collections
  uv run scripts\\patreon_catalog.py "..." --collection "Beginner Lessons"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import websockets

# Force UTF-8 output — Windows cp1252 can't encode emoji from Patreon content
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CDP_URL = "http://localhost:9222"
DEFAULT_OUTPUT = r"C:\Users\Matt\agent-control\state\patreon_catalog.json"

# Scroll behaviour — tuned to look human
SCROLL_PX_MIN = 600
SCROLL_PX_MAX = 1000
SCROLL_DELAY_MIN = 1.5
SCROLL_DELAY_MAX = 5.0
MAX_SCROLLS = 300          # hard safety cap
STALE_LIMIT = 5            # consecutive zero-new-post scrolls → stop
PAGE_LOAD_WAIT = 8         # seconds after initial navigation
INITIAL_EXTRACT_WAIT = 3   # seconds before first extraction

# Stealth: occasional human-like micro-behaviours
READING_PAUSE_CHANCE = 0.20   # chance of a longer "reading" pause after new posts
READING_PAUSE_MIN = 5.0
READING_PAUSE_MAX = 12.0
MOUSE_MOVE_CHANCE = 0.65      # chance of a mouse wiggle before a scroll
SCROLL_UP_CHANCE = 0.10       # chance of a small scroll-back-up before continuing
SCROLL_UP_PX_MIN = 100
SCROLL_UP_PX_MAX = 300


# ---------------------------------------------------------------------------
# JavaScript: extract post metadata from the current DOM
# ---------------------------------------------------------------------------
EXTRACT_POSTS_JS = r"""
(function() {
    var posts = [];

    /* ---- collect unique post URLs with their anchors ---- */
    var urlMap = {}, urlOrder = [];
    var allA = document.querySelectorAll('a[href*="/posts/"]');
    for (var i = 0; i < allA.length; i++) {
        var href = allA[i].href;
        if (!href.match(/\/posts\/[\w-]*\d+/)) continue;
        var url = href.split('?')[0].split('#')[0];
        if (!urlMap[url]) { urlMap[url] = []; urlOrder.push(url); }
        urlMap[url].push(allA[i]);
    }

    /* ---- for each URL, extract metadata ---- */
    for (var u = 0; u < urlOrder.length; u++) {
        var url = urlOrder[u];
        var anchors = urlMap[url];

        /* best title = longest non-trivial anchor text */
        var bestTitle = '', bestAnchor = anchors[0];
        for (var j = 0; j < anchors.length; j++) {
            var t = anchors[j].textContent.trim();
            if (t.match(/^\d+$/) ||
                t.match(/^\d+\s*(like|comment|repl)/i) ||
                t.length < 3) continue;
            if (t.length > bestTitle.length && t.length < 500) {
                bestTitle = t;
                bestAnchor = anchors[j];
            }
        }

        /* walk up to find the post-card container */
        var card = bestAnchor;
        for (var k = 0; k < 12; k++) {
            if (!card.parentElement || card.parentElement === document.body) break;
            card = card.parentElement;
            if (card.tagName === 'ARTICLE' ||
                card.getAttribute('role') === 'article') break;
            var dt = card.getAttribute('data-tag') || '';
            if (dt && dt.indexOf('post') >= 0) break;
            if ((card.offsetHeight || 0) > 120 && (card.offsetWidth || 0) > 400) {
                var pH = card.parentElement
                    ? (card.parentElement.offsetHeight || 0) : 0;
                if (pH > card.offsetHeight * 1.5) break;
            }
        }

        /* title fallback: headings inside the card */
        if (!bestTitle || bestTitle.length < 3) {
            var hs = card.querySelectorAll('h1,h2,h3,h4,[data-tag*="title"]');
            for (var h = 0; h < hs.length; h++) {
                var ht = hs[h].textContent.trim();
                if (ht.length > bestTitle.length && ht.length < 300) bestTitle = ht;
            }
        }
        if (!bestTitle) {
            var slug = url.split('/posts/')[1] || '';
            bestTitle = slug.replace(/-\d+$/, '').replace(/-/g, ' ');
        }

        /* date: prefer datetime attr on <time>, fall back to text */
        var date = '';
        var times = card.querySelectorAll('time');
        for (var ti = 0; ti < times.length; ti++) {
            date = times[ti].getAttribute('datetime') ||
                   times[ti].textContent.trim();
            if (date) break;
        }

        /* post type detection */
        var cHTML = card.innerHTML || '';
        var hasVideo =
            /vimeo|video-embed|video_embed|youtube|wistia|player/i.test(cHTML) ||
            card.querySelector(
                'video,iframe[src*="vimeo"],iframe[src*="youtube"]'
            ) !== null;
        var hasAudio =
            /audio-player|podcast/i.test(cHTML) ||
            card.querySelector('audio') !== null;
        var hasPoll = card.querySelector('[data-tag*="poll"]') !== null;
        var imgCount = card.querySelectorAll('img').length;

        var type = 'text';
        if (hasVideo) type = 'video';
        else if (hasAudio) type = 'audio';
        else if (hasPoll) type = 'poll';
        else if (imgCount > 2) type = 'image';

        /* lock detection */
        var isLocked = false;
        var svgs = card.querySelectorAll('svg');
        for (var s = 0; s < svgs.length; s++) {
            if (/lock/i.test(svgs[s].outerHTML || '')) {
                isLocked = true; break;
            }
        }
        if (!isLocked &&
            /unlock|join to|locked post|for members only/i
                .test(card.textContent || '')) {
            isLocked = true;
        }

        /* preview text (first substantive paragraph, <=200 chars) */
        var preview = '';
        var paras = card.querySelectorAll('p,span[data-tag*="content"]');
        for (var p = 0; p < paras.length; p++) {
            var pt = paras[p].textContent.trim();
            if (pt.length > 20 && pt !== bestTitle &&
                !/^\d+\s*(like|comment)/i.test(pt)) {
                preview = pt.substring(0, 200);
                break;
            }
        }

        posts.push({
            title: bestTitle,
            url: url,
            date: date,
            type: type,
            has_video: hasVideo,
            is_locked: isLocked,
            preview: preview
        });
    }

    return JSON.stringify(posts);
})()
"""

EXTRACT_CREATOR_JS = r"""
(function() {
    /* try page title: "Posts | Creator Name | Patreon" */
    var title = document.title || '';
    var parts = title.split('|').map(function(s) { return s.trim(); });
    if (parts.length >= 2) {
        for (var i = 0; i < parts.length; i++) {
            if (parts[i] !== 'Patreon' && parts[i] !== 'Posts' &&
                parts[i] !== 'Creating' && parts[i].length > 1) {
                return parts[i];
            }
        }
    }
    /* fallback: first h1 on the page */
    var h1 = document.querySelector('h1');
    if (h1) return h1.textContent.trim();
    return '';
})()
"""

EXTRACT_COLLECTIONS_JS = r"""
(function() {
    var collections = [];
    var seen = {};

    /* Strategy 1: links whose href contains /collection/ */
    var links = document.querySelectorAll('a[href*="/collection/"]');
    for (var i = 0; i < links.length; i++) {
        var href = links[i].href;
        var url = href.split('?')[0].split('#')[0];
        if (seen[url]) continue;
        seen[url] = true;

        /* Extract a clean title.
           innerText respects block-level breaks (title and description
           are usually in separate divs → separated by \n).  If the link
           text is all one line, split at the lowercase→uppercase boundary
           where title ends and description begins ("PortfolioThis…"). */
        var rawText = links[i].innerText
            ? links[i].innerText.trim()
            : links[i].textContent.trim();
        var textLines = rawText.split(/\n/);
        var name = textLines[0].trim();

        /* Still concatenated inline?  Split at case boundary. */
        if (name.length > 50 && textLines.length <= 1) {
            var sp = name.match(
                /^(.{5,}?(?:[a-z!?.’”]|—))([A-Z])/
            );
            if (sp) name = sp[1];
        }

        /* Strip trailing post count ("41 posts") */
        name = name.replace(/\d+\s*posts?\s*$/i, '').trim();

        /* Fallback: walk up to parent */
        if (!name || name.length < 2) {
            var parent = links[i].parentElement;
            if (parent) {
                name = (parent.innerText || parent.textContent || '').trim()
                    .split(/\n/)[0].trim()
                    .replace(/\d+\s*posts?\s*$/i, '').trim();
            }
        }
        /* Hard cap on length */
        if (name && name.length > 200) {
            name = name.substring(0, 200).replace(/\s+\S*$/, '');
        }
        if (!name || name.length < 2) continue;

        /* Try to grab a post count if visible nearby */
        var countText = '';
        var card = links[i].closest('[data-tag], article, [role="article"]')
                   || links[i].parentElement;
        if (card) {
            var m = (card.textContent || '').match(/(\d+)\s*posts?/i);
            if (m) countText = m[1];
        }

        collections.push({
            name: name,
            url: url,
            post_count: countText ? parseInt(countText, 10) : null
        });
    }

    /* Strategy 2: look for tabs / nav items labelled as collections */
    if (collections.length === 0) {
        var navLinks = document.querySelectorAll(
            'nav a, [role="tablist"] a, [data-tag*="nav"] a'
        );
        for (var j = 0; j < navLinks.length; j++) {
            var text = navLinks[j].textContent.trim();
            if (/collect/i.test(text) && navLinks[j].href) {
                collections.push({
                    name: text,
                    url: navLinks[j].href.split('?')[0],
                    post_count: null
                });
            }
        }
    }

    return JSON.stringify(collections);
})()
"""


# ---------------------------------------------------------------------------
# CDP helpers (mirrors patreon_capture_remote.py)
# ---------------------------------------------------------------------------
async def get_ws_url() -> str:
    """Get the CDP WebSocket debugger URL from Chrome's /json endpoint."""
    data = urllib.request.urlopen(f"{CDP_URL}/json").read()
    pages = json.loads(data)
    page = next(p for p in pages if p["type"] == "page")
    return page["webSocketDebuggerUrl"]


async def _make_cdp_helpers(ws):
    """Return (cdp, js, move_mouse) closures bound to *ws*."""
    msg_id = [0]

    async def cdp(method: str, params: dict | None = None) -> dict:
        msg_id[0] += 1
        mid = msg_id[0]
        payload = {"id": mid, "method": method, "params": params or {}}
        await ws.send(json.dumps(payload))
        while True:
            resp = json.loads(await ws.recv())
            if resp.get("id") == mid:
                return resp

    async def js(expr: str, await_promise: bool = False):
        """Evaluate JS in the page context and return the value."""
        params: dict = {"expression": expr, "returnByValue": True}
        if await_promise:
            params["awaitPromise"] = True
        r = await cdp("Runtime.evaluate", params)
        inner = r.get("result", {})
        if "exceptionDetails" in inner:
            return None
        return inner.get("result", {}).get("value")

    async def move_mouse(x: float, y: float) -> None:
        """Dispatch a mouse-move via CDP Input domain."""
        await cdp("Input.dispatchMouseEvent", {
            "type": "mouseMoved", "x": x, "y": y,
        })

    return cdp, js, move_mouse


# ---------------------------------------------------------------------------
# List collections
# ---------------------------------------------------------------------------
async def list_collections(creator_url: str) -> list[dict]:
    """Navigate to a creator page and extract available collections.

    Returns a list of dicts: [{name, url, post_count}, ...].
    Outputs a machine-readable ``COLLECTIONS:`` line on stdout.
    """
    ws_url = await get_ws_url()

    async with websockets.connect(
        ws_url, max_size=50 * 1024 * 1024, ping_interval=30,
    ) as ws:
        cdp, js, move_mouse = await _make_cdp_helpers(ws)

        # Strip /posts suffix — collections live on the creator root or a
        # dedicated /collections tab, not the /posts feed.
        base_url = creator_url.rstrip("/")
        if base_url.endswith("/posts"):
            base_url = base_url[: -len("/posts")]

        print(f"  [nav] Navigating to {base_url}", flush=True)
        await cdp("Page.navigate", {"url": base_url})
        await asyncio.sleep(PAGE_LOAD_WAIT)

        # First pass — extract whatever is already visible
        raw = await js(EXTRACT_COLLECTIONS_JS)
        collections: list[dict] = json.loads(raw) if raw else []

        # Scroll down a couple of times in case collections are below the fold
        for _ in range(3):
            prev = len(collections)
            scroll_px = random.randint(SCROLL_PX_MIN, SCROLL_PX_MAX)
            await js(f"window.scrollBy(0, {scroll_px}); 'scrolled'")
            await asyncio.sleep(random.uniform(SCROLL_DELAY_MIN, SCROLL_DELAY_MAX))

            if random.random() < MOUSE_MOVE_CHANCE:
                await move_mouse(
                    random.randint(400, 1200), random.randint(200, 700),
                )
                await asyncio.sleep(random.uniform(0.1, 0.3))

            raw = await js(EXTRACT_COLLECTIONS_JS)
            batch = json.loads(raw) if raw else []
            seen_urls = {c["url"] for c in collections}
            for c in batch:
                if c["url"] not in seen_urls:
                    collections.append(c)

            if len(collections) == prev:
                break  # no new collections appeared

        # ---- Output ----------------------------------------------------------
        print(f"\n{'=' * 50}", flush=True)
        print(f"  Collections found: {len(collections)}", flush=True)
        for i, c in enumerate(collections, 1):
            count = f" ({c['post_count']} posts)" if c.get("post_count") else ""
            print(f"    {i}. {c['name']}{count}", flush=True)
            print(f"       {c['url']}", flush=True)
        print(f"{'=' * 50}", flush=True)

        print(f"COLLECTIONS:{json.dumps(collections)}", flush=True)
        result = {"ok": True, "count": len(collections), "collections": collections}
        print(f"RESULT:{json.dumps(result)}", flush=True)

        return collections


async def find_collection_url(creator_url: str, name: str) -> str | None:
    """List collections and return the URL whose name matches *name*.

    Tries exact match first, then case-insensitive substring.
    """
    collections = await list_collections(creator_url)

    # Exact (case-insensitive)
    for c in collections:
        if c["name"].lower() == name.lower():
            return c["url"]
    # Substring
    for c in collections:
        if name.lower() in c["name"].lower():
            print(
                f"  [info] Partial match: '{name}' → '{c['name']}'",
                flush=True,
            )
            return c["url"]

    print(f"  ERROR: no collection matching '{name}'", file=sys.stderr, flush=True)
    available = ", ".join(c["name"] for c in collections) or "(none found)"
    print(f"  Available: {available}", file=sys.stderr, flush=True)
    return None


# ---------------------------------------------------------------------------
# Main cataloging flow
# ---------------------------------------------------------------------------
async def catalog_posts(
    creator_url: str,
    *,
    known_urls: set[str] | None = None,
    output_path: str | None = None,
) -> dict:
    """Scroll through a creator's posts page and catalog every post.

    When *known_urls* is provided (--new-only mode), scrolling stops as soon
    as a post URL from the known set is encountered.  Only the posts above
    that point (i.e. newer) are included in the output.

    Returns the catalog dict.
    """
    output = Path(output_path or DEFAULT_OUTPUT)
    output.parent.mkdir(parents=True, exist_ok=True)

    ws_url = await get_ws_url()

    async with websockets.connect(
        ws_url, max_size=50 * 1024 * 1024, ping_interval=30,
    ) as ws:
        cdp, js, move_mouse = await _make_cdp_helpers(ws)

        # ---- Navigate --------------------------------------------------------
        print(f"  [nav] Navigating to {creator_url}", flush=True)
        await cdp("Page.navigate", {"url": creator_url})
        await asyncio.sleep(PAGE_LOAD_WAIT)

        # ---- Extract creator name --------------------------------------------
        creator_name = await js(EXTRACT_CREATOR_JS) or ""
        print(f"  [info] Creator: {creator_name or '(unknown)'}", flush=True)

        # ---- Scroll-and-extract loop -----------------------------------------
        all_posts: list[dict] = []
        seen_urls: set[str] = set()
        stale_count = 0
        hit_known = False

        await asyncio.sleep(INITIAL_EXTRACT_WAIT)

        for scroll_num in range(MAX_SCROLLS):
            # Extract posts currently in the DOM
            raw = await js(EXTRACT_POSTS_JS)
            batch: list[dict] = []
            if raw:
                try:
                    batch = json.loads(raw)
                except json.JSONDecodeError:
                    pass

            new_in_batch = 0
            for post in batch:
                url = post.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                # In --new-only mode, stop when we see a known post
                if known_urls and url in known_urls:
                    hit_known = True
                    print(f"  [stop] Hit known post: {url}", flush=True)
                    break

                post["recorded"] = False
                all_posts.append(post)
                new_in_batch += 1

            total = len(all_posts)
            if new_in_batch > 0:
                stale_count = 0
                print(
                    f"  [scroll {scroll_num + 1}] +{new_in_batch} new "
                    f"(total: {total})",
                    flush=True,
                )
            else:
                stale_count += 1

            # ---- Stop conditions ---------------------------------------------
            if hit_known:
                print(
                    f"  [stop] Found {total} new post(s) above known content",
                    flush=True,
                )
                break

            if stale_count >= STALE_LIMIT:
                print(
                    f"  [done] No new posts for {STALE_LIMIT} consecutive "
                    f"scrolls — end of feed",
                    flush=True,
                )
                break

            # Check if we're at the very bottom of the page
            at_bottom = await js(
                "(window.scrollY + window.innerHeight "
                ">= document.body.scrollHeight - 50)"
            )
            if at_bottom and stale_count >= 2:
                print("  [done] Reached bottom of page", flush=True)
                break

            # ---- Human-like micro-behaviours ---------------------------------

            # Reading pause: ~20% chance after discovering new posts
            if new_in_batch > 0 and random.random() < READING_PAUSE_CHANCE:
                pause = random.uniform(READING_PAUSE_MIN, READING_PAUSE_MAX)
                print(
                    f"  [scroll] Reading pause ({pause:.0f}s)...",
                    flush=True,
                )
                await asyncio.sleep(pause)

            # Mouse wiggle: move cursor to a random spot in the content area
            if random.random() < MOUSE_MOVE_CHANCE:
                mx = random.randint(400, 1200)
                my = random.randint(200, 700)
                await move_mouse(mx, my)
                await asyncio.sleep(random.uniform(0.1, 0.4))

            # Occasional small scroll-up (re-reading something)
            if random.random() < SCROLL_UP_CHANCE:
                up_px = random.randint(SCROLL_UP_PX_MIN, SCROLL_UP_PX_MAX)
                await js(f"window.scrollBy(0, -{up_px}); 'scrolled-up'")
                await asyncio.sleep(random.uniform(1.0, 2.0))

            # ---- Scroll down (randomised distance) --------------------------
            scroll_px = random.randint(SCROLL_PX_MIN, SCROLL_PX_MAX)
            await js(f"window.scrollBy(0, {scroll_px}); 'scrolled'")
            delay = random.uniform(SCROLL_DELAY_MIN, SCROLL_DELAY_MAX)
            await asyncio.sleep(delay)

        # ---- Build catalog ---------------------------------------------------
        cataloged_at = datetime.now(timezone.utc).isoformat()
        creator_base = creator_url.rstrip("/")
        if creator_base.endswith("/posts"):
            creator_base = creator_base[: -len("/posts")]

        video_count = sum(1 for p in all_posts if p.get("has_video"))

        # Date range from extracted dates
        dates = [p["date"] for p in all_posts if p.get("date")]
        date_range = ""
        if dates:
            date_range = (
                f"{dates[-1]} .. {dates[0]}" if len(dates) > 1 else dates[0]
            )

        catalog = {
            "creator": creator_name,
            "creator_url": creator_base,
            "cataloged_at": cataloged_at,
            "total_posts": len(all_posts),
            "posts": all_posts,
        }

        # ---- Save to disk ---------------------------------------------------
        output.write_text(
            json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8",
        )
        print(f"\n  [save] Catalog written to {output}", flush=True)

        # ---- Summary --------------------------------------------------------
        type_counts: dict[str, int] = {}
        for p in all_posts:
            t = p.get("type", "text")
            type_counts[t] = type_counts.get(t, 0) + 1

        print(f"\n{'=' * 50}", flush=True)
        print(f"  Creator:     {creator_name}", flush=True)
        print(f"  Total posts: {len(all_posts)}", flush=True)
        print(f"  Videos:      {video_count}", flush=True)
        if date_range:
            print(f"  Date range:  {date_range}", flush=True)
        print(f"  Types:       {type_counts}", flush=True)
        print(f"{'=' * 50}", flush=True)

        # Machine-readable lines for the orchestrator script
        print(f"CATALOG:{output}", flush=True)
        result = {
            "ok": True,
            "total_posts": len(all_posts),
            "video_count": video_count,
            "catalog_path": str(output),
            "date_range": date_range,
        }
        print(f"RESULT:{json.dumps(result)}", flush=True)

        return catalog


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
async def async_main() -> int:
    parser = argparse.ArgumentParser(
        description="Patreon content cataloger via CDP (runs on obs-machine)",
    )
    parser.add_argument(
        "creator_url",
        help="Patreon creator posts page URL",
    )
    parser.add_argument(
        "--known-urls",
        metavar="FILE",
        help=(
            "JSON file containing an array of already-known post URLs.  "
            "Scrolling stops at the first known URL (--new-only mode)."
        ),
    )
    parser.add_argument(
        "--list-collections",
        action="store_true",
        help="List available collections from the creator page and exit",
    )
    parser.add_argument(
        "--collection",
        metavar="NAME",
        help="Catalog posts from a specific collection (by name or substring)",
    )
    parser.add_argument(
        "--output", "-o",
        metavar="PATH",
        default=DEFAULT_OUTPUT,
        help=f"Output path for the catalog JSON (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    # ---- List-collections mode (quick query, no catalog) ---------------------
    if args.list_collections:
        print(f"\n{'=' * 50}", flush=True)
        print("Patreon Collection Lister", flush=True)
        print(f"  URL: {args.creator_url}", flush=True)
        print(f"{'=' * 50}\n", flush=True)
        await list_collections(args.creator_url)
        return 0

    # ---- Collection mode: resolve name → URL, then catalog that page ---------
    target_url = args.creator_url
    collection_name: str | None = None
    if args.collection:
        print(f"\n{'=' * 50}", flush=True)
        print("Patreon Collection Cataloger", flush=True)
        print(f"  URL:        {args.creator_url}", flush=True)
        print(f"  Collection: {args.collection}", flush=True)
        print(f"{'=' * 50}\n", flush=True)

        resolved = await find_collection_url(args.creator_url, args.collection)
        if not resolved:
            return 1
        target_url = resolved
        collection_name = args.collection
        print(f"  [info] Cataloging collection at {target_url}\n", flush=True)

    # ---- Normal / new-only catalog mode --------------------------------------
    # Load known URLs if provided
    known: set[str] | None = None
    if args.known_urls:
        known_path = Path(args.known_urls)
        if not known_path.exists():
            print(
                f"ERROR: known-urls file not found: {known_path}",
                file=sys.stderr,
            )
            return 1
        try:
            data = json.loads(known_path.read_text(encoding="utf-8"))
            known = set(data)
            print(f"  [info] Loaded {len(known)} known URL(s)", flush=True)
        except (json.JSONDecodeError, TypeError) as e:
            print(f"ERROR: invalid known-urls JSON: {e}", file=sys.stderr)
            return 1

    if not collection_name:
        print(f"\n{'=' * 50}", flush=True)
        print("Patreon Content Cataloger", flush=True)
        print(f"  URL:  {target_url}", flush=True)
        print(f"  Mode: {'new-only' if known else 'full catalog'}", flush=True)
        print(f"{'=' * 50}\n", flush=True)

    await catalog_posts(
        target_url,
        known_urls=known,
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
