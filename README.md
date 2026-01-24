# Battery Tapo Control

Automatic battery monitoring and charging control system that intelligently manages a Tapo smart plug based on laptop battery levels.

## Overview

This script monitors your device's battery percentage and automatically controls a Tapo smart plug to manage charging. It includes:

- **Automatic charging control** based on battery thresholds
- **Night mode** with scheduled charging windows
- **Notifications** via ntfy.sh when critical events occur
- **Connection monitoring** with alerts for power outages or plug unavailability
- **Rotating log file** management with configurable file size limits

## Features

- **Smart Charging Modes**:
  - **Always Charging Mode** (day hours): Charger always remains ON
  - **Auto Charge Mode** (night hours): Charger turns OFF when battery reaches HIGH_THRESHOLD and ON when it drops below LOW_THRESHOLD

- **Critical Monitoring**: Detects when battery is critically low and Tapo plug is unreachable (potential power outage)

- **Notification System**: Sends push notifications for:
  - Connection restored
  - Connection lost / potential power outage
  - Critical battery + unreachable plug scenarios

- **Logging**: Comprehensive rotating file logging with console output

## Requirements

- Python 3.7+
- `psutil` - Battery monitoring
- `python-dotenv` - Environment variable loading
- `plugp100` - Tapo device control
- `aiohttp` - Async HTTP client for notifications

## Installation

1. Install dependencies:
```bash
pip install psutil python-dotenv plugp100 aiohttp
```

2. Create a `.env` file in the project directory with your configuration (see Configuration below)

## Configuration

Create a `sample.env` or `.env` file with the following variables:

### Battery Thresholds
- `LOW_THRESHOLD` (default: 35) - Battery % to turn charger ON in night mode
- `HIGH_THRESHOLD` (default: 85) - Battery % to turn charger OFF in night mode
- `CRITICAL_THRESHOLD` (default: 25) - Battery % considered critical for alerts

### Tapo Smart Plug
- `TAPO_IP` - IP address of your Tapo plug
- `TAPO_EMAIL` - Email for Tapo account authentication
- `TAPO_PASSWORD` - Password for Tapo account authentication

### Timing
- `START_TIME` (default: "22:00") - When night mode begins (HH:MM format)
- `END_TIME` (default: "12:00") - When night mode ends (HH:MM format)
- `CHECK_INTERVAL` (default: 300) - Battery check interval in seconds

### Notifications
- `NTFY_TOPIC` (default: "https://ntfy.sh/<topic>") - Your ntfy.sh topic URL for push notifications

### Logging
- `LOG_FILE` (default: "battery_tapo_log.txt") - Path to log file
- `MAX_LOG_SIZE` (default: 5242880 / 5MB) - Maximum log file size before rotation
- `BACKUP_COUNT` (default: 3) - Number of backup log files to keep

### Testing
- `FORCE_NOTIFY_TEST` (default: "False") - Set to "true" to test notifications even when not critical

## Usage

Run the script:
```bash
python battery_tapo_control.py
```

To run in the background (Linux/Mac):
```bash
nohup python battery_tapo_control.py > /dev/null 2>&1 &
```

To run as a service on Linux, create a systemd service file.

## How It Works

1. **Battery Monitoring**: Continuously checks battery percentage at regular intervals
2. **Connection Management**: Automatically reconnects if Tapo plug becomes unavailable
3. **Mode-Based Control**:
   - Outside scheduled hours: Keeps charger ON
   - During scheduled hours: Manages charging based on battery thresholds
4. **Alert System**: Sends notifications for connection issues and critical battery states
5. **Logging**: Records all actions and status changes for troubleshooting

## Logging

All activities are logged to the specified log file with timestamps and severity levels (INFO, WARNING, ERROR). Logs are rotated automatically based on file size to prevent excessive disk usage.

## Troubleshooting

- **"Tapo connect failed"**: Check IP address, email, and password credentials in .env
- **"Tapo Plug unreachable"**: Verify plug is powered on and connected to network
- **"Unable to read battery info"**: Ensure psutil can access battery information
- **Notifications not working**: Verify ntfy.sh topic URL is correct and reachable
