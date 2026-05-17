import sys
import argparse
import asyncio
import psutil
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from dotenv import load_dotenv
import os
from plugp100.common.credentials import AuthCredential
from plugp100.new.device_factory import connect, DeviceConnectConfiguration
from plugp100.new.components.on_off_component import OnOffComponent
from aiohttp import ClientSession

load_dotenv()

# Parse CLI arguments
parser = argparse.ArgumentParser(description="Battery Tapo Control Monitor")
parser.add_argument(
    "--mode",
    choices=["schedule", "always_on", "auto"],
    default="schedule",
    help="Charging mode: schedule (time-based), always_on (always on), auto (threshold-based)"
)
args = parser.parse_args()
CHARGE_MODE = args.mode

# ---------------- CONFIG ----------------
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))
LOW_THRESHOLD = int(os.getenv("LOW_THRESHOLD", "35"))
HIGH_THRESHOLD = int(os.getenv("HIGH_THRESHOLD", "85"))
CRITICAL_THRESHOLD = int(os.getenv("CRITICAL_THRESHOLD", "25"))

FORCE_NOTIFY_TEST = os.getenv("FORCE_NOTIFY_TEST", "False").lower() == "true"

TAPO_IP = os.getenv("TAPO_IP", "")
TAPO_EMAIL = os.getenv("TAPO_EMAIL", "")
TAPO_PASSWORD = os.getenv("TAPO_PASSWORD", "")

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "https://ntfy.sh/<topic>")

LOG_FILE = os.getenv("LOG_FILE", "battery_tapo_log.txt")
MAX_LOG_SIZE = int(os.getenv("MAX_LOG_SIZE", str(5 * 1024 * 1024)))
BACKUP_COUNT = int(os.getenv("BACKUP_COUNT", "3"))

START_TIME_STR = os.getenv("START_TIME", "22:00")
END_TIME_STR = os.getenv("END_TIME", "12:00")
START_TIME = datetime.strptime(START_TIME_STR, "%H:%M").time()
END_TIME = datetime.strptime(END_TIME_STR, "%H:%M").time()
# ----------------------------------------

logger = logging.getLogger("BatteryTapoMonitor")
logger.setLevel(logging.INFO)

handler = RotatingFileHandler(LOG_FILE, maxBytes=MAX_LOG_SIZE, backupCount=BACKUP_COUNT)
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

console = logging.StreamHandler()
console.setFormatter(formatter)
logger.addHandler(console)

def log(msg, level="info"):
    getattr(logger, level)(msg)

def get_battery_percent():
    battery = psutil.sensors_battery()
    return battery.percent if battery else None

def is_schedule_window():
    now = datetime.now().time()
    if START_TIME <= END_TIME:
        return START_TIME <= now <= END_TIME
    return now >= START_TIME or now <= END_TIME


def is_battery_critical(percent):
    return percent < CRITICAL_THRESHOLD


def should_charge(mode, percent, plug_on, is_schedule_window):
    if mode == "always_on":
        return True

    if mode == "auto":
        if percent > HIGH_THRESHOLD:
            return False
        if percent < LOW_THRESHOLD:
            return True
        return plug_on

    if mode == "schedule":
        if not is_schedule_window:
            return True
        if percent > HIGH_THRESHOLD:
            return False
        if percent < LOW_THRESHOLD:
            return True
        return plug_on

    raise ValueError(f"Unsupported charging mode: {mode}")

async def send_ntfy(session: ClientSession, message: str, priority: int = 3):
    try:
        async with session.post(
            NTFY_TOPIC,
            data=message.encode("utf-8"),
            headers={
                "Content-Type": "text/plain",
                "Priority": str(priority),
            }
        ) as response:
            response.raise_for_status()
    except Exception as e:
        log(f"ntfy notification failed: {e}", "warning")

async def connect_plug():
    credentials = AuthCredential(TAPO_EMAIL, TAPO_PASSWORD)
    config = DeviceConnectConfiguration(host=TAPO_IP, credentials=credentials)
    device = await connect(config)
    await device.update()

    onoff = next(
        (c for c in device.get_device_components if isinstance(c, OnOffComponent)),
        None
    )
    return device, onoff

async def monitor_battery(session: ClientSession):
    device, onoff = None, None
    tapo_was_down = False
    critical_notified = False

    try:
        while True:
            percent = get_battery_percent()
            if percent is None:
                log("Unable to read battery info.", "warning")
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            battery_is_critical = is_battery_critical(percent)
            if not battery_is_critical:
                critical_notified = False

            if not device or not onoff:
                log("Connecting to Tapo plug...")
                try:
                    device, onoff = await connect_plug()
                    log("Connected to Tapo plug")

                    if tapo_was_down:
                        await send_ntfy(session, "✅ Power restored / Tapo plug reachable again.", priority=3)
                        tapo_was_down = False
                except Exception as e:
                    log(f"Tapo connect failed: {e}", "warning")
                    if not tapo_was_down and (FORCE_NOTIFY_TEST or battery_is_critical):
                        await send_ntfy(
                            session,
                            f"⚠️ Battery {percent}% and Tapo plug unreachable. Possible power outage.",
                            priority=5
                        )
                        tapo_was_down = True
                        if battery_is_critical:
                            critical_notified = True
                    device, onoff = None, None
                    await asyncio.sleep(CHECK_INTERVAL)  # Sleep on connection failure
                    continue

            try:
                await device.update()
            except Exception as e:
                log(f"Tapo Plug unreachable: {e}", "warning")
                if not tapo_was_down and (FORCE_NOTIFY_TEST or battery_is_critical):
                    await send_ntfy(
                        session,
                        f"⚠️ Battery {percent}% and Tapo plug unreachable. Possible power outage.",
                        priority=5
                    )
                    tapo_was_down = True
                    if battery_is_critical:
                        critical_notified = True
                device, onoff = None, None
                await asyncio.sleep(CHECK_INTERVAL)  # Fixed tight loop bug here
                continue

            assert device is not None
            assert onoff is not None

            if battery_is_critical and not critical_notified:
                await send_ntfy(
                    session,
                    f"⚠️ Battery {percent}% is critical in {CHARGE_MODE} mode.",
                    priority=5,
                )
                critical_notified = True

            schedule_window_active = CHARGE_MODE == "schedule" and is_schedule_window()
            should_enable_charging = should_charge(
                CHARGE_MODE,
                percent,
                onoff.device_on,
                schedule_window_active,
            )

            log(f"Battery: {percent}% | Plug is {'ON' if onoff.device_on else 'OFF'} | Mode: {CHARGE_MODE}")

            if should_enable_charging and not onoff.device_on:
                await onoff.turn_on()
            elif not should_enable_charging and onoff.device_on:
                await onoff.turn_off()

            await asyncio.sleep(CHECK_INTERVAL)

    except asyncio.CancelledError:
        log("Shutdown requested")
        raise

async def main():
    log(f"Battery monitor started with mode: {CHARGE_MODE}...")
    async with ClientSession() as session:
        await monitor_battery(session)

if __name__ == "__main__":
    try:
        # Modern Python 3.14+ compatible runtime setup
        loop_factory = asyncio.WindowsSelectorEventLoopPolicy().new_event_loop if sys.platform.startswith("win") else None
        asyncio.run(main(), loop_factory=loop_factory)
    except KeyboardInterrupt:
        sys.exit(0)
