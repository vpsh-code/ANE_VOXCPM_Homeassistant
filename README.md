# VoxCPMANE Wyoming Bridge

This project bridges [VoxCPMANE](https://github.com/0seba/VoxCPMANE) (Apple Neural Engine TTS) with [Home Assistant](https://www.home-assistant.io/) using the **Wyoming protocol**.

By leveraging the **Apple Neural Engine (ANE)**, the bridge enables **fully local**, **low‑latency**, and **high‑quality** text‑to‑speech on Apple Silicon Macs (M1, M2, M3, M4).

---

## Overview

- Runs VoxCPMANE locally on macOS
- Exposes TTS via Wyoming for Home Assistant
- Optimized for Apple Silicon (ANE-backed inference)
- No cloud dependencies

---

## Prerequisites

### Hardware
- Apple Silicon Mac (M1 or newer)

### Software
- Python **3.11+**
- [uv](https://docs.astral.sh/uv/) package manager (recommended)

---

## Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/vpsh-code/ANE_VOXCPM_Homeassistant.git
cd ANE_VOXCPM_Homeassistant
uv sync
```

---

## Usage

### Option 1: Manual Start (Foreground)

Recommended for testing and validation.

```bash
uv run run_vox.py
```

This starts:
- VoxCPMANE server on port **8000**
- Wyoming bridge on port **10330**

---

### Option 2: Background (Current Session)

```bash
nohup uv run run_vox.py > vox.log 2>&1 &
```

---

### Option 3: Persistent macOS Service (Recommended)

Runs automatically on login and restarts if it crashes.

#### 1. Generate LaunchAgent plist

Run from the project root:

```bash
cat <<EOF > com.voxcpmane.bridge.plist
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.voxcpmane.bridge</string>

    <key>ProgramArguments</key>
    <array>
        <string>$(which uv)</string>
        <string>run</string>
        <string>run_vox.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$(pwd)</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>$(pwd)/vox_stdout.log</string>

    <key>StandardErrorPath</key>
    <string>$(pwd)/vox_stderr.log</string>
</dict>
</plist>
EOF
```

#### 2. Register and start the service

```bash
cp com.voxcpmane.bridge.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.voxcpmane.bridge.plist
```

---

## Home Assistant Integration

### 1. Find Mac IP address

Wi‑Fi:
```bash
ipconfig getifaddr en0
```

Ethernet:
```bash
ipconfig getifaddr en1
```

### 2. Add Wyoming integration

- Home Assistant → **Settings → Devices & Services**
- **Add Integration**
- Search for **Wyoming**

**Configuration:**
- Host: `<Mac IP address>`
- Port: `10330`

---

## Features

- **ANE Acceleration** – Dedicated Apple Neural Engine inference
- **Low Latency** – Streaming audio output
- **Fully Local** – No external APIs or cloud services
- **Voice Library** – 29 local voices including:
  - `af_heart`
  - `am_adam`
  - `bf_lily`

---

## Network Requirements

- Mac and Home Assistant must be on the **same local network**
- No firewall blocking port **10330**

---

## Repository Structure (Expected)

```
ANE_VOXCPM_Homeassistant/
├── run_vox.py
├── pyproject.toml
├── uv.lock
├── README.md
```

---

## Notes

- Designed for macOS only
- Optimized for Apple Silicon
- Intended for Home Assistant Wyoming TTS usage

---

## License

Refer to the upstream VoxCPMANE project for licensing details.