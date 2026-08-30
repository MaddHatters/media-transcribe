"""Record a single Patreon video. Runs fully on the obs-machine.

Usage (via scheduled task or directly):
    py -3 record_one.py <URL> <FILENAME>

Requires:
    - Chrome running with --remote-debugging-port=9222 (use agent.ps1 launch-chrome)
    - OBS running with WebSocket enabled on port 4455
    - OBS Desktop Audio set to "default" (not a specific device ID)
    - OBS Window Capture or Display Capture enabled and targeting Chrome
"""
import json, asyncio, urllib.request, websockets, time, sys, os, shutil, ctypes
import obsws_python as obs

VIDEO_URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.patreon.com/posts/119811238"
FILENAME = sys.argv[2] if len(sys.argv) > 2 else "Masterclass 19 - Munger Mental Models"
DEST_DIR = r"D:\MasterClass Video Backup"
CDP_URL = "http://localhost:9222"
OBS_PASSWORD = "DK4HLJPKgslAhEgD"
LOG = r"C:\Users\Matt\agent-control\logs\record.log"

def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def focus_chrome():
    """Find and focus the Chrome window using Win32 API.
    Must be called from the interactive desktop session.
    """
    user32 = ctypes.windll.user32

    # Minimize all windows first (Win+D)
    user32.keybd_event(0x5B, 0, 0, 0)  # Win key down
    user32.keybd_event(0x44, 0, 0, 0)  # D key down
    user32.keybd_event(0x44, 0, 2, 0)  # D key up
    user32.keybd_event(0x5B, 0, 2, 0)  # Win key up
    time.sleep(1)

    # Find Chrome window by class name
    hwnd = user32.FindWindowW("Chrome_WidgetWin_1", None)
    if hwnd:
        user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.5)
        return True
    return False


async def main():
    # Clear log
    with open(LOG, "w") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} Recording: {FILENAME}\n")
        f.write(f"URL: {VIDEO_URL}\n\n")
    
    data = urllib.request.urlopen(f'{CDP_URL}/json').read()
    pages = json.loads(data)
    page = [p for p in pages if p['type'] == 'page'][0]
    ws_url = page['webSocketDebuggerUrl']
    
    async with websockets.connect(ws_url, max_size=50*1024*1024, ping_interval=30) as ws:
        mid = [0]
        async def cdp(method, params=None):
            mid[0] += 1
            m = mid[0]
            await ws.send(json.dumps({'id': m, 'method': method, 'params': params or {}}))
            while True:
                resp = json.loads(await ws.recv())
                if resp.get('id') == m:
                    return resp

        async def js(expr):
            r = await cdp('Runtime.evaluate', {'expression': expr, 'returnByValue': True})
            return r.get('result', {}).get('result', {}).get('value')

        async def real_click(x, y):
            await cdp('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})
            await cdp('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})

        # Step 1: Navigate
        log("[1/10] Navigating...")
        await js("if(document.fullscreenElement) document.exitFullscreen(); 'ok'")
        await asyncio.sleep(1)
        await cdp('Page.navigate', {'url': VIDEO_URL})
        await asyncio.sleep(10)

        # Step 2: Wait for player
        log("[2/10] Waiting for player...")
        duration = None
        for attempt in range(30):
            state = await js("""
            (function() {
                var v = document.querySelector('video');
                if (!v) return JSON.stringify({ready: false, reason: 'no video'});
                var d = v.duration;
                if (!d || isNaN(d) || d <= 0) return JSON.stringify({ready: false, reason: 'no duration'});
                return JSON.stringify({ready: true, duration: d});
            })()
            """)
            if state:
                s = json.loads(state)
                if s['ready']:
                    duration = s['duration']
                    log(f"  Duration: {duration:.0f}s ({duration/60:.1f}min)")
                    break
            await asyncio.sleep(2)
        if not duration:
            log("FAILED: Player never ready")
            return

        # Step 3: Pause + reset + UNMUTE
        log("[3/10] Reset to 0:00 + unmute...")
        await js("var v = document.querySelector('video'); v.pause(); v.currentTime = 0; v.muted = false; v.volume = 1.0; 'ok'")
        await asyncio.sleep(2)

        # Step 4: Fullscreen (TAC trick with retry + window focus)
        log("[4/10] Fullscreen...")

        fs = False
        for fs_attempt in range(3):
            # Focus Chrome window before each attempt
            focus_chrome()
            await asyncio.sleep(1)

            # Inject TAC trick click handler
            await js("""
            (function() {
                var v = document.querySelector('video');
                v.addEventListener('click', function handler() {
                    v.requestFullscreen();
                    v.removeEventListener('click', handler);
                }, {once: true});
                return 'ok';
            })()
            """)

            # Get video bounding box center
            bbox = json.loads(await js("""
            (function() {
                var v = document.querySelector('video');
                var r = v.getBoundingClientRect();
                return JSON.stringify({x: r.x + r.width/2, y: r.y + r.height/2});
            })()
            """))

            # CDP click to trigger fullscreen
            await real_click(bbox['x'], bbox['y'])
            await asyncio.sleep(2)

            fs = await js('!!document.fullscreenElement')
            if fs:
                log(f"  Fullscreen: True (attempt {fs_attempt + 1})")
                break
            else:
                log(f"  Fullscreen attempt {fs_attempt + 1}/3 failed — retrying")
                await asyncio.sleep(2)

        # Fallback: try F11 (browser fullscreen)
        if not fs:
            log("  Trying F11 fallback...")
            focus_chrome()
            await asyncio.sleep(1)
            # Send F11 via CDP
            await cdp('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'F11', 'code': 'F11', 'windowsVirtualKeyCode': 122})
            await cdp('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'F11', 'code': 'F11', 'windowsVirtualKeyCode': 122})
            await asyncio.sleep(2)
            # Try the TAC trick one more time now that browser is fullscreen
            await js("""
            (function() {
                var v = document.querySelector('video');
                v.addEventListener('click', function handler() {
                    v.requestFullscreen();
                    v.removeEventListener('click', handler);
                }, {once: true});
                return 'ok';
            })()
            """)
            bbox = json.loads(await js("""
            (function() {
                var v = document.querySelector('video');
                var r = v.getBoundingClientRect();
                return JSON.stringify({x: r.x + r.width/2, y: r.y + r.height/2});
            })()
            """))
            await real_click(bbox['x'], bbox['y'])
            await asyncio.sleep(2)
            fs = await js('!!document.fullscreenElement')
            if fs:
                log("  Fullscreen: True (F11 + TAC trick)")

        if not fs:
            log("FAILED: Fullscreen rejected after 3 attempts + F11 fallback")
            return

        # Step 5: Re-pause at 0:00 + confirm unmuted
        log("[5/10] Re-pause at 0:00...")
        await js("var v = document.querySelector('video'); v.pause(); v.currentTime = 0; v.muted = false; 'ok'")
        muted = await js("document.querySelector('video').muted")
        log(f"  Muted: {muted}")
        await asyncio.sleep(2)

        # Step 6: Hide cursor
        log("[6/10] Hiding cursor...")
        await cdp('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': 0, 'y': 0})
        await asyncio.sleep(2)

        # Step 7: Start OBS
        log("[7/10] Starting OBS...")
        c = obs.ReqClient(host='localhost', port=4455, password=OBS_PASSWORD, timeout=10)
        c.set_profile_parameter("Output", "FilenameFormatting", FILENAME)
        c.start_record()
        time.sleep(2)
        log("  Recording")

        # Step 8: Play from beginning
        log("[8/10] Playing...")
        await js("var v = document.querySelector('video'); v.currentTime = 0; v.muted = false; v.play(); 'ok'")
        await asyncio.sleep(3)
        state_str = await js("var v = document.querySelector('video'); JSON.stringify({ct: v.currentTime, paused: v.paused, muted: v.muted})")
        state = json.loads(state_str)
        log(f"  ct={state['ct']:.1f}s paused={state['paused']} muted={state['muted']}")
        
        if state['paused']:
            log("  Clicking to play...")
            await real_click(bbox['x'], bbox['y'])
            await asyncio.sleep(3)
        
        # Hide cursor again
        await cdp('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': 0, 'y': 0})

        # Step 9: Monitor
        log(f"[9/10] Monitoring (~{duration/60:.0f} min)...")
        stall_count = 0
        last_ct = -1
        while True:
            state = json.loads(await js("""
            (function() {
                var v = document.querySelector('video');
                return JSON.stringify({ct: v.currentTime, dur: v.duration, paused: v.paused, ended: v.ended, muted: v.muted});
            })()
            """))
            ct = state['ct']
            dur = state['dur']
            pct = (ct / dur * 100) if dur > 0 else 0
            log(f"  {ct:.0f}s / {dur:.0f}s ({pct:.1f}%)")
            
            if state['ended'] or (ct >= dur - 2 and dur > 0):
                log("  VIDEO ENDED")
                break
            
            # Ensure not muted
            if state['muted']:
                log("  Re-unmuting...")
                await js("document.querySelector('video').muted = false; 'ok'")
            
            # Stall detection
            if abs(ct - last_ct) < 0.5 and not state['paused']:
                stall_count += 1
                if stall_count > 6:
                    log("  STALLED - nudging")
                    await js("var v = document.querySelector('video'); v.currentTime += 0.5; v.play(); 'ok'")
                    stall_count = 0
            else:
                stall_count = 0
            last_ct = ct
            
            # Auto-resume if paused
            if state['paused'] and not state['ended']:
                log("  PAUSED - resuming")
                await js("document.querySelector('video').play(); 'ok'")
            
            await asyncio.sleep(30)

        # Step 10: Stop + cleanup
        log("[10/10] Stopping...")
        await asyncio.sleep(3)
        resp = c.stop_record()
        path = getattr(resp, 'output_path', None)
        log(f"  Saved: {path}")
        await js("if(document.fullscreenElement) document.exitFullscreen(); 'ok'")
        
        log("DONE")  # Video captured successfully — print before move

        # Move with retry (OBS holds file handle briefly after stop_record)
        if path and os.path.exists(path):
            size_mb = os.path.getsize(path) / (1024*1024)
            dest = os.path.join(DEST_DIR, f"{FILENAME}.mp4")
            os.makedirs(DEST_DIR, exist_ok=True)
            moved = False
            for attempt in range(6):  # up to 30 seconds
                try:
                    shutil.move(path, dest)
                    log(f"  Moved: {dest} ({size_mb:.1f} MB)")
                    moved = True
                    break
                except PermissionError:
                    if attempt < 5:
                        log(f"  File locked, retrying in 5s... ({attempt+1}/6)")
                        time.sleep(5)
                    else:
                        log(f"  ERROR: Could not move after 6 attempts: {path}")
            if not moved:
                log(f"  File saved at: {path} ({size_mb:.1f} MB)")

asyncio.run(main())
