# examples/telegram_signals_bot.py
#
# Telegram Signals Layer for PyQuotex
# ------------------------------------
# Monitors a Telegram channel for trading signals, detects direction
# from stickers/text (UP/CALL or DOWN/PUT), and executes trades
# on the Quotex practice account.

import re
import json
import time
import asyncio
import logging
import argparse
import configparser
from pathlib import Path

from telethon import TelegramClient, events
from pyquotex.stable_api import Quotex
from pyquotex.config import resource_path as quotex_resource_path

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("TelegramSignals")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "settings" / "config.ini"

config = configparser.ConfigParser(interpolation=None)
config.read(CONFIG_PATH, encoding="utf-8")

# Quotex credentials
QUOTEX_EMAIL = config.get("settings", "email")
QUOTEX_PASSWORD = config.get("settings", "password")

# Telegram credentials
TELEGRAM_API_ID = config.getint("telegram", "api_id")
TELEGRAM_API_HASH = config.get("telegram", "api_hash")
TELEGRAM_CHANNEL = config.get("telegram", "channel")

# Trading defaults
TRADE_AMOUNT = config.getfloat("trading", "amount", fallback=1.0)
TRADE_DURATION = config.getint("trading", "duration", fallback=60)
ACCOUNT_MODE = config.get("trading", "account_mode", fallback="PRACTICE").upper()

# How long (seconds) a pending signal stays valid before expiring
SIGNAL_EXPIRY_SECONDS = 600

# Quotex connection retry settings
MAX_CONNECT_RETRIES = 5
RETRY_DELAY_SECONDS = 3

# Telethon session file
SESSION_PATH = str(BASE_DIR / "settings" / "telegram_session")

# Quotex session file — must match where PyQuotex's load_session() reads from
SESSION_FILE = quotex_resource_path("session.json")

# ---------------------------------------------------------------------------
# Asset name normalisation helpers
# ---------------------------------------------------------------------------
ASSET_ALIASES = {
    "EUR CAD": "EURCAD",
    "EUR USD": "EURUSD",
    "EUR JPY": "EURJPY",
    "GBP USD": "GBPUSD",
    "GBP JPY": "GBPJPY",
    "USD JPY": "USDJPY",
    "USD CHF": "USDCHF",
    "AUD USD": "AUDUSD",
    "AUD CHF": "AUDCHF",
    "AUD CAD": "AUDCAD",
    "AUD JPY": "AUDJPY",
    "NZD USD": "NZDUSD",
    "USD CAD": "USDCAD",
    "EUR GBP": "EURGBP",
    "EUR AUD": "EURAUD",
    "EUR NZD": "EURNZD",
    "EUR CHF": "EURCHF",
    "GBP AUD": "GBPAUD",
    "GBP CAD": "GBPCAD",
    "GBP CHF": "GBPCHF",
    "GBP NZD": "GBPNZD",
    "CAD JPY": "CADJPY",
    "CAD CHF": "CADCHF",
    "CHF JPY": "CHFJPY",
    "NZD JPY": "NZDJPY",
}

# Regex to find a FOREX pair like "EUR JPY", "GBPUSD", etc.
PAIR_PATTERN = re.compile(
    r"([A-Z]{3})\s*([A-Z]{3})",
    re.IGNORECASE,
)

# Regex to extract expiry - e.g. "1 mins EXPIRY", "5 min expiry", "2 minute"
EXPIRY_PATTERN = re.compile(
    r"(\d+)\s*min(?:s|ute|utes)?\s*(?:expiry)?",
    re.IGNORECASE,
)

# All indicators for direction (text keywords + sticker emoji)
CALL_INDICATORS = {"UP", "CALL", "👍", "☝️"}
PUT_INDICATORS = {"DOWN", "PUT", "👎", "👇"}


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class PendingSignal:
    """Holds a parsed signal that is waiting for a direction."""

    def __init__(self, asset: str, duration: int):
        self.asset = asset
        self.duration = duration
        self.created_at = time.time()

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > SIGNAL_EXPIRY_SECONDS

    def __repr__(self):
        return f"PendingSignal(asset={self.asset}, duration={self.duration}s)"


# The single pending signal (only one at a time)
pending_signal: PendingSignal | None = None


# ---------------------------------------------------------------------------
# Signal parsing
# ---------------------------------------------------------------------------

def normalise_asset(raw: str) -> str:
    """Normalise an asset string like 'EUR JPY' -> 'EURJPY'."""
    raw_upper = raw.upper().strip()
    if raw_upper in ASSET_ALIASES:
        return ASSET_ALIASES[raw_upper]
    return raw_upper.replace(" ", "")


def parse_signal_message(text: str) -> PendingSignal | None:
    """
    Try to parse a signal message.

    Expected pattern (flexible):
        EUR JPY (checkmark)
        Wait FOR DIRECTION
        1 mins EXPIRY
        (DEFAULT TIME)

    Returns a PendingSignal if asset pair found, else None.
    """
    if not text:
        return None

    clean = text.upper()

    # Must contain a trading cue
    has_direction_cue = any(kw in clean for kw in [
        "WAIT FOR DIRECTION",
        "WAIT FOR",
        "DIRECTION",
        "EXPIRY",
    ])

    # Find asset pair
    pair_match = PAIR_PATTERN.search(clean)
    if not pair_match:
        return None

    # Only treat as signal if there's some trading cue
    if not has_direction_cue:
        if "\u2705" not in text and "\U0001f525" not in text:  # checkmark, fire emoji
            return None

    raw_pair = f"{pair_match.group(1)} {pair_match.group(2)}"
    asset = normalise_asset(raw_pair)

    # Parse expiry duration
    expiry_match = EXPIRY_PATTERN.search(text)
    duration = int(expiry_match.group(1)) * 60 if expiry_match else TRADE_DURATION

    return PendingSignal(asset=asset, duration=duration)


def detect_direction(text: str, sticker=None) -> str | None:
    """
    Detect trade direction from a message or sticker.

    Returns 'call', 'put', or None.
    """
    # 1. Check sticker
    if sticker is not None:
        # Check sticker emoji attribute
        emoji = getattr(sticker, "emoji", None) or ""
        if emoji in CALL_INDICATORS:
            return "call"
        if emoji in PUT_INDICATORS:
            return "put"

        # Check sticker alt text for keywords
        alt = ""
        for attr in sticker.attributes:
            alt_text = getattr(attr, "alt", "") or ""
            alt += alt_text.upper()
        for kw in CALL_INDICATORS:
            if kw in alt:
                return "call"
        for kw in PUT_INDICATORS:
            if kw in alt:
                return "put"

    # 2. Check message text
    if text:
        upper = text.upper()
        for kw in CALL_INDICATORS:
            if kw in upper or kw in text:
                return "call"
        for kw in PUT_INDICATORS:
            if kw in upper or kw in text:
                return "put"

    return None


# ---------------------------------------------------------------------------
# Playwright browser login (bypasses Cloudflare)
# ---------------------------------------------------------------------------

async def acquire_session_via_browser(headless: bool = False):
    """
    Use Playwright with the REAL installed Chrome browser to log into Quotex.
    Uses a persistent browser profile (settings/browser_data) so cookies
    and login state survive across runs — you only log in once.

    KEEPS THE BROWSER OPEN so the websocket can run through Chrome
    (bypasses Cloudflare TLS fingerprinting).

    Args:
        headless: If True, run without a visible window (for VPS).
                  If False (default), show the window for CAPTCHA/2FA.

    Returns (playwright, context, page, token) on success, or None on failure.
    """
    from playwright.async_api import async_playwright

    # Persistent browser profile — survives restarts
    browser_data_dir = str(BASE_DIR / "settings" / "browser_data")

    logger.info("Launching Chrome (browser stays open for WebSocket)...")
    if not headless:
        logger.info("A Chrome window will open. Complete any CAPTCHA/2FA if prompted.")

    try:
        pw = await async_playwright().start()
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=browser_data_dir,
            channel="chrome",
            headless=headless,
            accept_downloads=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-dev-shm-usage"
            ],
        )

        page = context.pages[0] if context.pages else await context.new_page()

        # Navigate to login page
        login_url = "https://qxbroker.com/en/sign-in"
        logger.info("Navigating to %s", login_url)
        await page.goto(login_url, wait_until="domcontentloaded", timeout=60000)

        # Check if already logged in (redirected to /trade)
        if "/trade" in page.url:
            logger.info("Already logged in from previous session!")
        else:
            # Wait for the email input to appear
            try:
                await page.wait_for_selector(
                    'input[name="email"], input[type="email"]',
                    timeout=20000,
                )
            except Exception:
                pass

            # Auto-fill credentials
            try:
                email_input = page.locator('input[name="email"], input[type="email"]').first
                await email_input.fill(QUOTEX_EMAIL)
                await asyncio.sleep(0.5)

                password_input = page.locator('input[name="password"], input[type="password"]').first
                await password_input.fill(QUOTEX_PASSWORD)
                await asyncio.sleep(0.5)

                submit_btn = page.locator('button[type="submit"], .modal-sign__block-btn').first
                await submit_btn.click()
                logger.info("Credentials submitted. Waiting for login...")
            except Exception as e:
                logger.warning("Could not auto-fill: %s", e)
                logger.info("Please log in manually in the Chrome window.")

            # Wait for redirect to /trade (up to 120s for manual login/2FA)
            logger.info("Waiting for login to complete (up to 120s)...")
            try:
                await page.wait_for_url("**/trade", timeout=120000)
            except Exception:
                if "/trade" not in page.url:
                    logger.error("Login did not complete. URL: %s", page.url)
                    await context.close()
                    await pw.stop()
                    return None

        logger.info("Login successful! Extracting session data...")
        await asyncio.sleep(3)  # Let page fully initialise

        # Extract token
        token = await page.evaluate(
            "() => { try { return window.settings.token } catch(e) { return null } }"
        )
        if not token:
            logger.error("Could not extract session token from page.")
            await context.close()
            await pw.stop()
            return None

        # Extract user-agent
        user_agent = await page.evaluate("navigator.userAgent")

        # Extract cookies as string
        cookies_list = await context.cookies()
        cookie_str = "; ".join(
            f"{c['name']}={c['value']}" for c in cookies_list
            if "qxbroker" in c.get("domain", "")
        )

        # Save to session.json (for token reference)
        session_data = {
            "cookies": cookie_str,
            "token": token,
            "user_agent": user_agent,
        }
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(json.dumps(session_data, indent=4))
        logger.info("Session saved. Browser stays open for WebSocket.")

        # Return browser objects — caller must keep them alive!
        return pw, context, page, token

    except Exception as e:
        logger.exception("Browser login failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Quotex connection with retry
# ---------------------------------------------------------------------------

async def connect_quotex_with_retry(client: Quotex, max_retries: int = MAX_CONNECT_RETRIES) -> bool:
    """
    Attempt to connect to Quotex with retry logic.
    Only deletes session.json AFTER all retries are exhausted,
    so that a valid cached token can be reused across retries.
    Returns True on success, False on failure.
    """
    for attempt in range(1, max_retries + 1):
        try:
            logger.info("Quotex connection attempt %d/%d...", attempt, max_retries)
            check_connect, message = await client.connect()
            if check_connect:
                logger.info("Connected to Quotex successfully!")
                return True
            else:
                logger.warning("Connection returned False: %s", message)
        except Exception as e:
            logger.warning("Connection attempt %d failed: %s", attempt, e)

        if attempt < max_retries:
            logger.info("Retrying in %d seconds...", RETRY_DELAY_SECONDS)
            await asyncio.sleep(RETRY_DELAY_SECONDS)

    # Only delete the session file after ALL retries are exhausted
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
        logger.info("Removed stale session.json after all retries failed.")

    logger.error("Failed to connect to Quotex after %d attempts.", max_retries)
    return False


# ---------------------------------------------------------------------------
# Trading
# ---------------------------------------------------------------------------

async def sniper_entry(
    quotex_client: Quotex,
    asset_name: str,
    direction: str,
    signal: PendingSignal,
    wait_window: float = 30.0,
    tick_count: int = 2  # Number of ticks (pips) the price must move for a better entry
) -> bool:
    """
    Watches real-time ticks for a better entry price.
    For CALL: waits for a dip. For PUT: waits for a spike.
    """
    logger.info("Sniper mode: Waiting up to %ds for a better %s entry...", int(wait_window), direction.upper())
    
    # Subscribe to ensure we get realtime prices
    quotex_client.start_candles_stream(asset_name, 60)
    
    start_time = time.time()
    entry_price = None
    target_price = None
    
    # Get initial ticks to find baseline
    all_ticks = await quotex_client.get_realtime_price(asset_name)
    start_idx = len(all_ticks)
    
    while time.time() - start_time < wait_window:
        all_ticks = await quotex_client.get_realtime_price(asset_name)
        new_ticks = all_ticks[start_idx:]
        
        if all_ticks and entry_price is None:
            # Calculate the exact timestamp of the candle that completed BEFORE the direction was received
            direction_time = int(start_time)  # start_time = time.time() when direction sticker arrived
            current_candle_start = direction_time - (direction_time % 60)
            target_candle_time = current_candle_start - 60
            
            # 1. Attempt to get the TRUE CLOSE price of that exact candle using historical data
            try:
                # Fetch enough history to ensure we get the target candle (300 seconds = 5 mins)
                candles = await asyncio.wait_for(quotex_client.get_candles(asset_name, time.time(), 300, 60), timeout=3.0)
                if candles:
                    for c in candles:
                        if c["time"] == target_candle_time:
                            entry_price = float(c["close"])
                            logger.info("Found exact signal reference candle (Time: %s) close price: %.5f", target_candle_time, entry_price)
                            break
                    
                    # Fallback if the exact timestamp wasn't found in the array for some reason
                    if entry_price is None and len(candles) >= 2:
                        entry_price = float(candles[-2]["close"])
                        logger.info("Target candle time not matched, falling back to previous candle close: %.5f", entry_price)
            except Exception as e:
                logger.warning("Failed to fetch historical candle close, falling back to ticks: %s", e)

            # 2. Fallback if get_candles fails: try to find it in ticks, or just use the first tick we saw
            if entry_price is None:
                for tick in all_ticks:
                    if tick["time"] >= current_candle_start:
                        entry_price = tick["price"]
                        break
                if entry_price is None and new_ticks:
                    entry_price = new_ticks[0]["price"]
                
            if entry_price is not None:
                # Auto-detect tick size: JPY pairs (price > 10) use 0.001, others use 0.00001
                tick_size = 0.001 if entry_price > 10 else 0.00001
                dip_amount = tick_count * tick_size
                if direction.lower() == "call":
                    target_price = entry_price - dip_amount
                else:
                    target_price = entry_price + dip_amount
                logger.info("Sniper baseline: %.5f | Target: %.5f (tick_size=%.5f, ticks=%d)", entry_price, target_price, tick_size, tick_count)
                
        if target_price is not None and new_ticks:
            latest_price = new_ticks[-1]["price"]
            
            if direction.lower() == "call" and latest_price <= target_price:
                logger.info("Sniper CALL triggered! Price dipped to %.5f", latest_price)
                quotex_client.api.realtime_price[asset_name] = all_ticks[-10:]
                return True
            elif direction.lower() == "put" and latest_price >= target_price:
                logger.info("Sniper PUT triggered! Price spiked to %.5f", latest_price)
                quotex_client.api.realtime_price[asset_name] = all_ticks[-10:]
                return True
                
        await asyncio.sleep(0.2)
        
    logger.warning("Sniper window expired. No better entry found. Skipping trade.")
    if all_ticks:
        quotex_client.api.realtime_price[asset_name] = all_ticks[-10:]
    return False


async def execute_trade(quotex_client: Quotex, signal: PendingSignal, direction: str):
    """Execute a trade on Quotex based on the parsed signal."""
    logger.info(
        "PREPARING TRADE: %s | %s | %ds | $%.2f",
        signal.asset, direction.upper(), signal.duration, TRADE_AMOUNT,
    )

    try:
        # Ensure connection (lazy connect / reconnect)
        is_connected = await quotex_client.check_connect()
        if not is_connected:
            logger.info("Not connected to Quotex. Connecting now...")
            connected = await connect_quotex_with_retry(quotex_client)
            if not connected:
                logger.error("Could not connect to Quotex. Trade skipped.")
                return

        # Verify asset is available
        asset_name, asset_data = await quotex_client.get_available_asset(
            signal.asset, force_open=True
        )

        if not asset_data or len(asset_data) < 3 or not asset_data[2]:
            logger.warning("Asset %s is currently CLOSED. Skipping trade.", signal.asset)
            return

        logger.info("Asset %s is open.", asset_name)

        # --- Smart Sniper Entry ---
        good_entry = await sniper_entry(quotex_client, asset_name, direction, signal, wait_window=30.0)
        if not good_entry:
            return

        # Place the trade
        status, buy_info = await quotex_client.buy(
            TRADE_AMOUNT, asset_name, direction, signal.duration
        )

        if status:
            logger.info(
                "Trade placed! Asset: %s | Direction: %s | Amount: $%.2f | Duration: %ds",
                asset_name, direction.upper(), TRADE_AMOUNT, signal.duration,
            )
            logger.info("Buy info: %s", buy_info)

            balance = await quotex_client.get_balance()
            logger.info("Current balance: $%.2f", balance)
        else:
            logger.error("Trade FAILED. Status: %s | Info: %s", status, buy_info)

    except Exception as e:
        logger.exception("Error executing trade: %s", e)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(headless: bool = False):
    global pending_signal

    logger.info("=" * 60)
    logger.info("🤖 Telegram Signals Bot for PyQuotex")
    logger.info("=" * 60)

    # --- Launch browser and log into Quotex (stays open for WebSocket) ---
    result = await acquire_session_via_browser(headless=headless)
    if result is None:
        logger.error(
            "Could not log into Quotex via browser. "
            "Please try again or check your credentials."
        )
        return

    pw_instance, browser_context, browser_page, token = result
    logger.info("Browser logged in. Token: %s...", token[:10])

    # --- Quotex setup (uses browser page for WebSocket) ---
    quotex_client = Quotex(
        email=QUOTEX_EMAIL,
        password=QUOTEX_PASSWORD,
        lang="en",
        root_path=str(BASE_DIR),
    )
    quotex_client.set_account_mode(ACCOUNT_MODE)
    quotex_client.set_browser_page(browser_page)  # Route WS through Chrome
    logger.info("Quotex client initialised (%s mode, browser WebSocket).", ACCOUNT_MODE)

    # --- Telegram setup ---
    logger.info("Connecting to Telegram...")
    tg_client = TelegramClient(SESSION_PATH, TELEGRAM_API_ID, TELEGRAM_API_HASH, connection_retries=None, timeout=10, request_retries=5)

    await tg_client.start()
    logger.info("Connected to Telegram")

    # Resolve channel entity
    try:
        try:
            channel_entity = await tg_client.get_entity(int(TELEGRAM_CHANNEL))
        except (ValueError, TypeError):
            channel_entity = await tg_client.get_entity(TELEGRAM_CHANNEL)
        channel_name = getattr(channel_entity, 'title', TELEGRAM_CHANNEL)
        logger.info("Monitoring channel: %s", channel_name)
    except Exception as e:
        logger.error("Could not resolve channel '%s': %s", TELEGRAM_CHANNEL, e)
        await tg_client.disconnect()
        await browser_context.close()
        await pw_instance.stop()
        return

    # --- Event handler ---
    @tg_client.on(events.NewMessage(chats=channel_entity))
    async def on_new_message(event):
        global pending_signal

        msg = event.message
        text = msg.text or msg.message or ""
        sticker = msg.sticker

        logger.info(
            "New message: %s",
            text[:120] if text else f"[Sticker: emoji={getattr(sticker, 'emoji', '?') if sticker else 'N/A'}]",
        )

        # --- Step 1: Try to parse a new signal FIRST ---
        signal = parse_signal_message(text)
        if signal:
            if pending_signal:
                logger.info("Replacing old pending signal: %s", pending_signal)
            pending_signal = signal
            logger.info("New signal parsed: %s", signal)
            logger.info("Waiting for direction sticker/message...")
            return

        # --- Step 2: Try to detect direction (for a pending signal) ---
        if pending_signal and not pending_signal.is_expired:
            direction = detect_direction(text, sticker)
            if direction:
                logger.info(
                    "Direction detected: %s for pending signal %s",
                    direction.upper(), pending_signal,
                )
                # Run the trade in the background so it doesn't block Telegram events
                asyncio.create_task(execute_trade(quotex_client, pending_signal, direction))
                pending_signal = None
                return

        # Expire stale signals
        if pending_signal and pending_signal.is_expired:
            logger.warning("Pending signal expired: %s", pending_signal)
            pending_signal = None

        # --- Step 3: Standalone direction (no pending signal) ---
        direction = detect_direction(text, sticker)
        if direction:
            logger.info(
                "Direction '%s' received but no pending signal. Ignoring.",
                direction.upper(),
            )

    # --- Background pre-connection to Quotex ---
    async def _pre_connect():
        """Try to connect to Quotex in the background so it's ready for trades."""
        await asyncio.sleep(2)  # Let Telegram fully settle first
        logger.info("Background: pre-connecting to Quotex...")
        try:
            connected = await connect_quotex_with_retry(quotex_client, max_retries=3)
            if connected:
                balance = await quotex_client.get_balance()
                logger.info("Background: Quotex ready | Balance: $%.2f", balance)
            else:
                logger.warning(
                    "Background: Quotex pre-connect failed. "
                    "Will retry when a trade signal arrives."
                )
        except Exception as e:
            logger.warning("Background: Quotex pre-connect error: %s", e)

    asyncio.ensure_future(_pre_connect())

    # --- Run ---
    logger.info("=" * 60)
    logger.info("Bot is running. Listening for signals...")
    logger.info("   Channel: %s", TELEGRAM_CHANNEL)
    logger.info("   Account: %s | Amount: $%.2f | Default Duration: %ds",
                ACCOUNT_MODE, TRADE_AMOUNT, TRADE_DURATION)
    logger.info("   Press Ctrl+C to stop.")
    logger.info("=" * 60)

    # --- Active Connection Supervisors ---
    async def telegram_supervisor():
        """Keeps Telegram connection alive and forces a crash if it completely drops."""
        while await tg_client.is_user_authorized():
            try:
                await asyncio.wait_for(tg_client.get_me(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("Telegram ping timed out (silent drop suspected).")
                # Telethon will attempt auto-reconnect, but if you want PM2 to handle it:
                # raise ConnectionError("Telegram connection dead")
            except Exception as e:
                logger.warning("Telegram ping error: %s", e)
            await asyncio.sleep(60)

    async def quotex_supervisor():
        """Keeps Quotex websocket alive."""
        while True:
            try:
                if await quotex_client.check_connect():
                    await asyncio.wait_for(quotex_client.get_balance(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("Quotex ping timed out.")
            except Exception as e:
                logger.warning("Quotex ping error: %s", e)
            await asyncio.sleep(60)

    try:
        # Run the supervisors and the passive listener concurrently
        await asyncio.gather(
            telegram_supervisor(),
            quotex_supervisor(),
            tg_client.run_until_disconnected()
        )
    except Exception as e:
        logger.error("Main loop error: %s", e)
    finally:
        try:
            await tg_client.disconnect()
        except Exception:
            pass
        try:
            await quotex_client.close()
        except Exception:
            pass
        # Close browser
        try:
            await browser_context.close()
        except Exception:
            pass
        try:
            await pw_instance.stop()
        except Exception:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Telegram Signals Bot for PyQuotex")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser login in headless mode (for VPS without display)",
    )
    args = parser.parse_args()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(main(headless=args.headless))
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    finally:
        # Suppress Telethon cleanup errors
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()
