"""Browser-based WebSocket client for Quotex (Cloudflare bypass).

Instead of Python's websocket-client (which gets TLS-fingerprinted and
blocked by Cloudflare), this keeps a real Chrome browser alive via
Playwright and intercepts the WebSocket that the Quotex trade page
naturally creates.

Usage:
    page = ...  # Playwright page already on /trade
    client = BrowserWebsocketClient(api, page)
    await client.start()
    # Messages flow through the same on_message pipeline as WebsocketClient
"""

import json
import asyncio
import logging

from .. import global_value

logger = logging.getLogger(__name__)


class BrowserWebsocketClient:
    """Drop-in async replacement for WebsocketClient that uses Playwright."""

    def __init__(self, api, page):
        """
        Args:
            api:  QuotexAPI instance (same as WebsocketClient expects)
            page: A live Playwright Page on the Quotex /trade page
        """
        self.api = api
        self.page = page
        self._ws = None          # Playwright WebSocket object (read-only listener)
        self._connected = False
        self._closed = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def start(self):
        """Navigate to trade, intercept the WS, inject a send helper."""

        # 1. Inject script BEFORE page load to capture WebSocket from creation
        await self.page.add_init_script("""
            // Track all WebSocket instances created by the page
            window._qxWsInstances = [];
            const _OrigWebSocket = window.WebSocket;

            window.WebSocket = function(...args) {
                const ws = new _OrigWebSocket(...args);
                window._qxWsInstances.push(ws);
                if (ws.url && (ws.url.includes('ws2.') || ws.url.includes('socket.io'))) {
                    window._qxWsRef = ws;
                }
                return ws;
            };
            window.WebSocket.prototype = _OrigWebSocket.prototype;
            window.WebSocket.CONNECTING = _OrigWebSocket.CONNECTING;
            window.WebSocket.OPEN = _OrigWebSocket.OPEN;
            window.WebSocket.CLOSING = _OrigWebSocket.CLOSING;
            window.WebSocket.CLOSED = _OrigWebSocket.CLOSED;

            // Helper for Python to send through the captured WS
            window._qxSend = function(msg) {
                // Try the tracked reference first
                if (window._qxWsRef && window._qxWsRef.readyState === 1) {
                    window._qxWsRef.send(msg);
                    return true;
                }
                // Fallback: search all instances
                for (var i = window._qxWsInstances.length - 1; i >= 0; i--) {
                    var ws = window._qxWsInstances[i];
                    if (ws.readyState === 1 && ws.url &&
                        (ws.url.includes('ws2.') || ws.url.includes('socket.io'))) {
                        window._qxWsRef = ws;
                        ws.send(msg);
                        return true;
                    }
                }
                return false;
            };
        """)

        # 2. Set up WS interception for Playwright's event system
        ws_future = asyncio.get_event_loop().create_future()

        def _on_ws(ws):
            if "ws2." in ws.url or "socket.io" in ws.url:
                if not ws_future.done():
                    ws_future.set_result(ws)

        self.page.on("websocket", _on_ws)

        # 3. Navigate/reload trade page (triggers init script + fresh WS)
        trade_url = "https://qxbroker.com/en/trade"
        logger.info("Navigating to trade page (with WS capture)...")
        await self.page.goto(trade_url, wait_until="domcontentloaded", timeout=60000)

        # 4. Wait for the WS to appear (max 30s)
        logger.info("Waiting for Quotex WebSocket connection...")
        try:
            self._ws = await asyncio.wait_for(ws_future, timeout=30)
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for WebSocket on trade page.")
            global_value.check_websocket_if_error = True
            global_value.websocket_error_reason = "Browser WS timeout"
            return

        logger.info("Browser WebSocket connected: %s", self._ws.url)

        # 5. Create shim for delegating to original WebsocketClient.on_message
        self._ws_shim = _BrowserWsShim(self.api, self.send)

        # 6. Listen for incoming frames
        self._ws.on("framereceived", self._on_frame_received)
        self._ws.on("close", self._on_ws_close)

        # 6. Wait for the page's own Socket.IO auth to complete
        #    The trade page's JS handles authorization and subscriptions
        #    automatically — we just listen for frames.
        await asyncio.sleep(5)

        # 7. Manually set auth flags since the page already authenticated
        #    (the auth frame arrived before our listener was attached)
        global_value.check_accepted_connection = 1
        global_value.check_rejected_connection = 0
        self._connected = True
        global_value.check_websocket_if_connect = 1

        # 8. Extract account/balance data from page JS
        try:
            balance_data = await self.page.evaluate("""() => {
                try {
                    const s = window.settings || {};
                    return {
                        demoBalance: parseFloat(s.demoBalance || s.demo_balance || 0),
                        liveBalance: parseFloat(s.liveBalance || s.live_balance || 0),
                        isDemo: s.isDemo != null ? s.isDemo : 1
                    };
                } catch(e) { return null; }
            }""")
            if balance_data:
                self.api.account_balance = balance_data
                # NOTE: Do NOT override self.api.account_type here —
                # it was already set to PRACTICE/LIVE by set_account_mode().
                logger.info("Balance loaded from page: demo=$%.2f, live=$%.2f",
                           float(balance_data.get("demoBalance", 0)),
                           float(balance_data.get("liveBalance", 0)))
        except Exception as e:
            logger.warning("Could not extract balance from page: %s", e)

        # 9. Send fresh subscription requests so our frame listener receives
        #    the responses (the initial data frames were missed).
        asset_name = self.api.current_asset
        period = self.api.current_period
        for msg in [
            '42["instruments/update",{"asset":"%s","period":%d}]' % (asset_name, period),
            '42["indicator/list"]',
            '42["drawing/load"]',
            '42["tick"]',
            '42["chart_notification/get"]',
            '42["pending/list"]',
        ]:
            await self.send(msg)
            await asyncio.sleep(0.3)

        # Wait for instruments to arrive
        for _ in range(20):  # 4 seconds max
            if self.api.instruments is not None:
                logger.info("Instruments data received (%d assets).",
                           len(self.api.instruments) if isinstance(self.api.instruments, list) else 0)
                break
            await asyncio.sleep(0.2)
        else:
            logger.warning("Instruments data not yet received — trades may hang.")

        logger.info("Browser WebSocket ready (page handles auth).")

    async def send(self, message: str):
        """Send a message through the browser WebSocket."""
        if self._closed:
            return
        try:
            result = await self.page.evaluate(f"window._qxSend({json.dumps(message)})")
            if not result:
                logger.warning("Browser WS send failed (not connected).")
        except Exception as e:
            logger.error("Browser WS send error: %s", e)

    async def close(self):
        """Close the browser WS bridge."""
        self._closed = True
        self._connected = False

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    def _on_frame_received(self, payload):
        """Called by Playwright when a WS frame arrives.

        Delegates to the original WebsocketClient.on_message logic
        so all message types (instruments, balance, buy results, etc.)
        are handled identically.
        """
        # Import here to avoid circular imports
        from .client import WebsocketClient

        # Playwright gives us a string — exactly like websocket-client does.
        # Pass it through the original on_message handler.
        # We create a fake "wss" arg (the handler barely uses it — only for .send("2")).
        message = payload  # keep as string, just like websocket-client

        # Reuse the original handler's logic by calling it as a function
        # with self.api (same api object the handler expects)
        WebsocketClient.on_message(self._ws_shim, None, message)

    def _on_ws_close(self):
        """Called when the browser WS closes."""
        logger.info("Browser WebSocket closed.")
        self._connected = False
        global_value.check_websocket_if_connect = 0


class _BrowserWsShim:
    """Minimal shim that acts like WebsocketClient for on_message delegation.

    The original on_message accesses self.api and self.wss.send().
    This shim provides both, routing sends through the browser WS.
    """

    def __init__(self, api, send_func):
        self.api = api
        self._send_func = send_func  # async func — we wrap it
        self.wss = self  # on_message calls self.wss.send("2") for pong

    def send(self, data):
        """Sync send stub — used by on_message for pong ("2")."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._send_func(data))
        except Exception:
            pass

