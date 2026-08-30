"""Single-query player detection — identifies the active player and returns a handler."""
from __future__ import annotations

import json

from src.players.base import DetectionResult
from src.players.mux import MuxPlayer
from src.players.vimeo import VimeoPlayer
from src.players.html5 import HTML5Player

DETECTION_JS = """
(function() {
    var iframe = document.querySelector("iframe[src*='vimeo']");
    if (iframe) return JSON.stringify({
        player: "vimeo", element: "iframe[src*='vimeo']",
        meta: {src: iframe.src}
    });

    var mux = document.querySelector("mux-player");
    if (mux) {
        var v = (mux.shadowRoot && mux.shadowRoot.querySelector('video'))
                || mux.querySelector('video');
        var d = v ? v.duration : 0;
        var rs = v ? v.readyState : 0;
        return JSON.stringify({
            player: "mux", element: "mux-player",
            meta: {duration: (isFinite(d) ? d : 0), readyState: rs}
        });
    }

    var yt = document.querySelector("iframe[src*='youtube']");
    if (yt) return JSON.stringify({
        player: "youtube", element: "iframe[src*='youtube']", meta: {}
    });

    var video = document.querySelector("video");
    if (video) return JSON.stringify({
        player: "html5", element: "video",
        meta: {duration: (isFinite(video.duration) ? video.duration : 0),
               src: video.currentSrc || ""}
    });

    return JSON.stringify({player: null, element: null, meta: {}});
})()
"""

_HANDLERS: dict[str, type] = {
    "vimeo": VimeoPlayer,
    "mux": MuxPlayer,
    "html5": HTML5Player,
}


async def detect_player(cdp, timeout: float = 30.0):
    raw = await cdp.js(DETECTION_JS)
    if not raw:
        return DetectionResult(player=None, element=None, meta={}), None
    data = json.loads(raw)
    result = DetectionResult(
        player=data.get("player"),
        element=data.get("element"),
        meta=data.get("meta", {}),
    )
    handler_cls = _HANDLERS.get(result.player)
    handler = handler_cls() if handler_cls else None
    return result, handler
