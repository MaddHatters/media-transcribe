#!/usr/bin/env python3
# Check what video player a Patreon post uses (Vimeo, native, etc).
# Deployed to obs-machine and run via SSH.
import asyncio
import json
import sys
import urllib.request

import websockets

CDP_URL = "http://localhost:9222"

DETECT_JS = r"""
(function() {
    var info = {};

    // Page title
    info.title = document.title;

    // Vimeo iframes
    var vimeoIframes = document.querySelectorAll("iframe[src*='vimeo']");
    info.vimeo_iframes = vimeoIframes.length;

    // All iframes
    var iframes = document.querySelectorAll('iframe');
    info.iframe_count = iframes.length;
    info.iframe_srcs = [];
    for (var i = 0; i < iframes.length; i++) {
        info.iframe_srcs.push(iframes[i].src || '(no src)');
    }

    // Native <video> elements
    var videos = document.querySelectorAll('video');
    info.video_count = videos.length;
    info.videos = [];
    for (var v = 0; v < videos.length; v++) {
        var vid = videos[v];
        var sources = vid.querySelectorAll('source');
        var srcList = [];
        for (var s = 0; s < sources.length; s++) {
            srcList.push({src: sources[s].src, type: sources[s].type});
        }
        info.videos.push({
            src: vid.src || '(no src)',
            currentSrc: vid.currentSrc || '(no currentSrc)',
            duration: vid.duration,
            paused: vid.paused,
            readyState: vid.readyState,
            width: vid.videoWidth,
            height: vid.videoHeight,
            sources: srcList
        });
    }

    // Check for player-related class names
    var playerEls = document.querySelectorAll('[class*="video"],[class*="player"],[class*="Player"]');
    info.player_elements = [];
    for (var p = 0; p < Math.min(playerEls.length, 10); p++) {
        info.player_elements.push({
            tag: playerEls[p].tagName,
            className: (playerEls[p].className || '').substring(0, 200),
            id: playerEls[p].id || ''
        });
    }

    // Check for video container / wrapper elements
    var containers = document.querySelectorAll('[data-tag*="video"],[data-tag*="media"],[role="application"]');
    info.container_count = containers.length;

    // Check full page for video-related keywords
    var html = document.documentElement.innerHTML;
    info.mentions_vimeo = html.indexOf('vimeo') >= 0;
    info.mentions_hls = html.indexOf('.m3u8') >= 0;
    info.mentions_dash = html.indexOf('.mpd') >= 0;
    info.mentions_mp4 = html.indexOf('.mp4') >= 0;
    info.mentions_webm = html.indexOf('.webm') >= 0;
    info.mentions_cloudfront = html.indexOf('cloudfront') >= 0;
    info.mentions_patreon_media = html.indexOf('c10.patreonusercontent') >= 0 || html.indexOf('stream.mux') >= 0;

    return JSON.stringify(info, null, 2);
})()
"""


async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.patreon.com/posts/119811238"

    # Get WS URL
    data = urllib.request.urlopen(f"{CDP_URL}/json").read()
    pages = json.loads(data)
    page = next(p for p in pages if p["type"] == "page")
    ws_url = page["webSocketDebuggerUrl"]

    async with websockets.connect(ws_url, max_size=50 * 1024 * 1024, ping_interval=30) as ws:
        msg_id = 0

        async def cdp(method, params=None):
            nonlocal msg_id
            msg_id += 1
            mid = msg_id
            await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            while True:
                resp = json.loads(await ws.recv())
                if resp.get("id") == mid:
                    return resp

        async def js(expr):
            r = await cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            inner = r.get("result", {})
            if "exceptionDetails" in inner:
                return f"ERROR: {json.dumps(inner['exceptionDetails'])}"
            return inner.get("result", {}).get("value")

        # Navigate
        print(f"Navigating to {url}...", flush=True)
        await cdp("Page.navigate", {"url": url})
        await asyncio.sleep(12)

        # Check video player
        result = await js(DETECT_JS)
        print(f"\n=== VIDEO PLAYER DETECTION ===")
        print(result)

        # Investigate HLS/Mux player API
        print("\n=== INVESTIGATING PLAYER API ===", flush=True)
        player_api = await js(r"""
        (function() {
            var info = {};
            /* Check for Mux player */
            info.hasMuxPlayer = typeof window.MuxPlayerElement !== 'undefined';
            info.hasMux = typeof window.mux !== 'undefined';
            /* Check for hls.js */
            info.hasHls = typeof window.Hls !== 'undefined';
            /* Check for MediaSource on the video */
            var v = document.querySelector('video');
            if (v) {
                info.videoSrc = (v.src || '').substring(0, 100);
                /* Check for custom properties on the video element */
                var customKeys = Object.keys(v).filter(function(k) {
                    return !k.startsWith('__react') && k !== 'style';
                });
                info.videoCustomKeys = customKeys.join(',');
            }
            /* Search global scope for player instances */
            var globals = Object.keys(window).filter(function(k) {
                return /player|hls|mux|video/i.test(k) && typeof window[k] === 'object' && window[k] !== null;
            });
            info.playerGlobals = globals.join(',');

            /* Walk the React fiber tree to find the video player component */
            var root = document.querySelector('[class*="VideoPlayerRoot"]');
            if (root) {
                var fiberKey = Object.keys(root).find(function(k) { return k.startsWith('__reactFiber'); });
                if (fiberKey) {
                    var fiber = root[fiberKey];
                    var components = [];
                    var node = fiber;
                    for (var i = 0; i < 30 && node; i++) {
                        if (node.memoizedState) {
                            var stateKeys = [];
                            var state = node.memoizedState;
                            for (var j = 0; j < 10 && state; j++) {
                                var val = state.memoizedState;
                                var type = typeof val;
                                if (val && type === 'object') {
                                    type = 'object{' + Object.keys(val).slice(0, 5).join(',') + '}';
                                }
                                stateKeys.push(type);
                                state = state.next;
                            }
                            if (stateKeys.length > 0) {
                                components.push({
                                    name: (node.type && node.type.name) || (node.type && node.type.displayName) || '(anon)',
                                    stateCount: stateKeys.length,
                                    stateTypes: stateKeys.join(' | ')
                                });
                            }
                        }
                        node = node.child;
                    }
                    info.fiberComponents = components;
                }
            }

            /* Check for MuxPlayerElement custom element */
            var muxEl = document.querySelector('mux-player, mux-video');
            info.hasMuxElement = !!muxEl;
            if (muxEl) info.muxElTag = muxEl.tagName;

            /* Check for global player state/store */
            var possibleStores = ['__NEXT_DATA__', '__NUXT__', '__APP_STATE__'];
            info.storesFound = possibleStores.filter(function(s) { return !!window[s]; });

            return JSON.stringify(info, null, 2);
        })()
        """)
        print(f"Player API: {player_api}", flush=True)

        # Deep dive: look at what's INSIDE the styled-component div that's blocking
        styled_div = await js(r"""
        (function() {
            var v = document.querySelector('video');
            if (!v) return 'no video';
            var rect = v.getBoundingClientRect();
            var cx = rect.x + rect.width / 2;
            var cy = rect.y + rect.height / 2;
            var el = document.elementFromPoint(cx, cy);
            if (!el) return 'no element';
            // Walk up to understand the structure
            var chain = [];
            var node = el;
            for (var i = 0; i < 8 && node && node !== document.body; i++) {
                chain.push({
                    tag: node.tagName,
                    className: typeof node.className === 'string' ? node.className.substring(0, 150) : String(node.className),
                    id: node.id || '',
                    children: node.children.length,
                    hasOnClick: !!(node.__reactProps$7279zj6snb8 || {}).onClick,
                    hasFiber: !!Object.keys(node).find(function(k) { return k.startsWith('__reactFiber'); })
                });
                node = node.parentElement;
            }
            return JSON.stringify(chain, null, 2);
        })()
        """)
        print(f"\nElement chain at video center:\n{styled_div}", flush=True)

        # Try to find and invoke the PARENT component's click handler
        parent_click = await js(r"""
        (function() {
            var v = document.querySelector('video');
            if (!v) return 'no video';
            var rect = v.getBoundingClientRect();
            var cx = rect.x + rect.width / 2;
            var cy = rect.y + rect.height / 2;
            var el = document.elementFromPoint(cx, cy);
            if (!el) return 'no element';
            // Walk up looking for any React onClick handler
            var node = el;
            for (var i = 0; i < 10 && node && node !== document.body; i++) {
                var keys = Object.keys(node);
                var propsKey = keys.find(function(k) { return k.startsWith('__reactProps'); });
                if (propsKey) {
                    var props = node[propsKey];
                    if (props && typeof props.onClick === 'function') {
                        return 'Found onClick on ' + node.tagName + ' class=' + String(node.className).substring(0, 50) + ' at depth ' + i;
                    }
                }
                node = node.parentElement;
            }
            return 'no onClick found in parent chain';
        })()
        """)
        print(f"\nParent onClick search: {parent_click}", flush=True)

        # Try to actually play the video with various approaches
        print("\n=== ATTEMPTING TO PLAY ===", flush=True)

        # What element is at the center of the video?
        elem_at_center = await js(r"""
        (function() {
            var v = document.querySelector('video');
            if (!v) return 'no video';
            var rect = v.getBoundingClientRect();
            var cx = rect.x + rect.width / 2;
            var cy = rect.y + rect.height / 2;
            var el = document.elementFromPoint(cx, cy);
            if (!el) return 'elementFromPoint returned null';
            return JSON.stringify({
                tag: el.tagName,
                className: (el.className || '').substring(0, 200),
                id: el.id,
                ariaLabel: el.getAttribute('aria-label'),
                role: el.getAttribute('role'),
                hasShadowRoot: !!el.shadowRoot,
                x: cx, y: cy
            });
        })()
        """)
        print(f"Element at video center: {elem_at_center}", flush=True)

        # Check what element is at the play button position
        elem_at_play = await js(r"""
        (function() {
            var btn = document.querySelector('button[aria-label="Play"]');
            if (!btn) return 'no play button';
            var rect = btn.getBoundingClientRect();
            var cx = rect.x + rect.width / 2;
            var cy = rect.y + rect.height / 2;
            var el = document.elementFromPoint(cx, cy);
            return JSON.stringify({
                topElement: {tag: el.tagName, className: (el.className || '').substring(0, 200)},
                button: {tag: btn.tagName, className: (btn.className || '').substring(0, 200)},
                isSameElement: el === btn,
                buttonIsVisible: window.getComputedStyle(btn).visibility !== 'hidden',
                buttonDisplay: window.getComputedStyle(btn).display,
                buttonOpacity: window.getComputedStyle(btn).opacity,
                buttonZIndex: window.getComputedStyle(btn).zIndex,
                x: cx, y: cy
            });
        })()
        """)
        print(f"Play button analysis: {elem_at_play}", flush=True)

        # Try pointer events instead of mouse events
        print("\nAttempt: PointerEvent dispatch...", flush=True)
        pointer_result = await js(r"""
        (function() {
            var btn = document.querySelector('button[aria-label="Play"]');
            if (!btn) {
                var overlay = document.querySelector('[class*="videoOverlayContainer"]');
                btn = overlay || document.querySelector('video');
            }
            if (!btn) return 'no target';

            var rect = btn.getBoundingClientRect();
            var cx = rect.x + rect.width / 2;
            var cy = rect.y + rect.height / 2;

            /* Dispatch full pointer sequence: pointerdown, pointerup, click */
            ['pointerdown', 'pointerup', 'click'].forEach(function(type) {
                var evt = new PointerEvent(type, {
                    bubbles: true, cancelable: true, view: window,
                    clientX: cx, clientY: cy,
                    pointerId: 1, pointerType: 'mouse',
                    isPrimary: true,
                    button: 0, buttons: type === 'pointerdown' ? 1 : 0
                });
                btn.dispatchEvent(evt);
            });
            return 'pointer events dispatched on ' + btn.tagName + ' ' + (btn.getAttribute('aria-label') || btn.className.substring(0, 50));
        })()
        """)
        print(f"  Result: {pointer_result}", flush=True)
        await asyncio.sleep(3)

        rs = await js("document.querySelector('video').readyState")
        paused = await js("document.querySelector('video').paused")
        print(f"  After pointer events: readyState={rs}, paused={paused}", flush=True)

        # Try React internal props
        print("\nChecking React internals...", flush=True)
        react_check = await js(r"""
        (function() {
            /* Find React fiber on player elements */
            var targets = [
                document.querySelector('[class*="VideoPlayerRoot"]'),
                document.querySelector('[class*="videoArea"]'),
                document.querySelector('button[aria-label="Play"]'),
                document.querySelector('video')
            ];
            var results = [];
            for (var i = 0; i < targets.length; i++) {
                var el = targets[i];
                if (!el) continue;
                var keys = Object.keys(el);
                var reactKey = keys.find(function(k) { return k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance') || k.startsWith('__reactProps'); });
                var info = {tag: el.tagName, label: el.getAttribute('aria-label') || (el.className || '').substring(0, 40)};
                if (reactKey) {
                    info.reactKey = reactKey;
                    var fiber = el[reactKey];
                    if (fiber && fiber.memoizedProps) {
                        var props = fiber.memoizedProps;
                        info.propKeys = Object.keys(props).filter(function(k) { return typeof props[k] === 'function'; }).join(',');
                    }
                    if (reactKey.startsWith('__reactProps')) {
                        var rp = el[reactKey];
                        info.rpKeys = Object.keys(rp).filter(function(k) { return typeof rp[k] === 'function'; }).join(',');
                    }
                }
                results.push(info);
            }
            return JSON.stringify(results, null, 2);
        })()
        """)
        print(f"React fiber analysis:\n{react_check}", flush=True)

        # Try invoking React onClick handler directly on the Play button
        print("\nAttempt: Invoke React onClick directly...", flush=True)
        react_click = await js(r"""
        (function() {
            var btn = document.querySelector('button[aria-label="Play"]');
            if (!btn) return 'no play button';
            var keys = Object.keys(btn);
            var propsKey = keys.find(function(k) { return k.startsWith('__reactProps'); });
            if (!propsKey) return 'no __reactProps found on button; keys: ' + keys.join(',');
            var props = btn[propsKey];
            if (!props) return 'props is null';
            if (typeof props.onClick === 'function') {
                props.onClick({
                    type: 'click',
                    target: btn,
                    currentTarget: btn,
                    preventDefault: function(){},
                    stopPropagation: function(){},
                    nativeEvent: new MouseEvent('click')
                });
                return 'onClick invoked!';
            }
            return 'no onClick handler; available: ' + Object.keys(props).filter(function(k){return typeof props[k]==='function';}).join(',');
        })()
        """)
        print(f"  Result: {react_click}", flush=True)
        await asyncio.sleep(3)

        rs = await js("document.querySelector('video').readyState")
        paused = await js("document.querySelector('video').paused")
        print(f"  After React onClick: readyState={rs}, paused={paused}", flush=True)

        # Check viewport and video position
        layout = await js(r"""
        (function() {
            var info = {};
            info.viewport = {w: window.innerWidth, h: window.innerHeight};
            info.screen = {w: screen.width, h: screen.height};
            info.devicePixelRatio = window.devicePixelRatio;
            info.scrollX = window.scrollX;
            info.scrollY = window.scrollY;

            var v = document.querySelector('video');
            if (v) {
                var rect = v.getBoundingClientRect();
                info.video_rect = {
                    x: rect.x, y: rect.y, w: rect.width, h: rect.height,
                    top: rect.top, left: rect.left, right: rect.right, bottom: rect.bottom
                };
                info.video_display = window.getComputedStyle(v).display;
                info.video_visibility = window.getComputedStyle(v).visibility;
                info.video_opacity = window.getComputedStyle(v).opacity;
                info.video_readyState = v.readyState;
                info.video_networkState = v.networkState;
                info.video_error = v.error ? v.error.message : null;
                info.video_src = (v.src || '').substring(0, 100);
                info.video_paused = v.paused;
            }

            /* Find any play buttons */
            var btns = document.querySelectorAll('button');
            info.buttons = [];
            for (var i = 0; i < Math.min(btns.length, 20); i++) {
                var br = btns[i].getBoundingClientRect();
                var txt = (btns[i].textContent || '').trim().substring(0, 50);
                var label = btns[i].getAttribute('aria-label') || '';
                if (txt.length > 0 || label.length > 0) {
                    info.buttons.push({
                        text: txt, label: label,
                        x: br.x, y: br.y, w: br.width, h: br.height
                    });
                }
            }

            /* Check for overlay/play elements specifically */
            var overlays = document.querySelectorAll('[class*="Overlay"], [class*="overlay"], [class*="PlayButton"], [class*="play-button"]');
            info.overlays = [];
            for (var o = 0; o < Math.min(overlays.length, 10); o++) {
                var or2 = overlays[o].getBoundingClientRect();
                info.overlays.push({
                    tag: overlays[o].tagName,
                    className: (overlays[o].className || '').substring(0, 150),
                    x: or2.x, y: or2.y, w: or2.width, h: or2.height
                });
            }

            return JSON.stringify(info, null, 2);
        })()
        """)
        print(f"\n=== LAYOUT & PLAYER STATE ===")
        print(layout)

        # Try scrolling video into view and re-check
        await js("var v = document.querySelector('video'); if(v) v.scrollIntoView({block:'center'}); 'ok'")
        await asyncio.sleep(2)

        layout2 = await js(r"""
        (function() {
            var v = document.querySelector('video');
            if (!v) return '{}';
            var rect = v.getBoundingClientRect();
            return JSON.stringify({
                video_rect_after_scroll: {x: rect.x, y: rect.y, w: rect.width, h: rect.height},
                readyState: v.readyState,
                paused: v.paused,
                scrollY: window.scrollY
            }, null, 2);
        })()
        """)
        print(f"\n=== AFTER SCROLL INTO VIEW ===")
        print(layout2)

asyncio.run(main())
