# VoxCPMANE Wyoming Bridge

This project bridges [VoxCPMANE](https://github.com/0seba/VoxCPMANE) (Apple Neural Engine TTS) with [Home Assistant](https://www.home-assistant.io/) using the **Wyoming protocol**.

By leveraging the **Apple Neural Engine (ANE)**, the bridge enables **fully local**, **low‑latency**, and **high‑quality** text‑to‑speech on Apple Silicon Macs (M1, M2, M3, M4).

Tested on Macbook Pro M3 with Tahoe OS 26.2
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
- Python **Python 3.11-3.12+**
- [uv](https://docs.astral.sh/uv/) package manager (recommended)


---

## Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/vpsh-code/ANE_VOXCPM_Homeassistant.git
cd ANE_VOXCPM_Homeassistant
uv sync
source .venv/bin/activate
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
- Wyoming bridge on port **10333**

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
ipconfig getifaddr en0 or
ipconfig  getifaddr en1 or
ipconfig getifaddr <your_interface>
```

### 2. Add Wyoming integration

- Home Assistant → **Settings → Devices & Services**
- **Add Integration**
- Search for **Wyoming**

**Configuration:**
- Host: `<Mac IP address>`
- Port: `10330`

### 3. Clone your voice (optional)

- Open Finder → Go → Go to Folder... ~/.cache/ane_tts/
- Place the voice file in .wav or .mp3 format eg: im_rajesh.wav
- Place transription file in .txt format eg: im_rajesh.txt
- Open Terminal and navigate to the root folder of this project and open vox_bridge.py file i.e nano vox_bridge.py
- Add the name of the voice in AVAILABLE_VOICES list eg: 'im_rajesh' and save the file.
- Restart the VoxCPMANE Wyoming Bridge service in the root folder i.e uv run run_vox.py
- Refresh the Wyoming integration in Home Assistant i.e Settings →  Devices & Services → Wyoming Protocol → Reload
- Settings → Voice Assistants → Select your pipeline → Select voxcpmane in Text-to-speech  → Select the cloneed voice from Voice* → click on Update

**Note : Do not clone a voice of someone without their permission.**

---

## Features

- **ANE Acceleration** – Dedicated Apple Neural Engine inference
- **Low Latency** – Streaming audio output
- **Fully Local** – No external APIs or cloud services
- **Voice Library** – 28 local voices including:
  - `af_heart`
  - `am_adam`
  - `bf_lily`
- **Clone your voice and make it available in voice assistant!**

---

## Network Requirements

- Mac and Home Assistant must be on the **same local network**
- No firewall blocking port **10330**

---

## Repository Structure (Expected)

```
ANE_VOXCPM_Homeassistant/
├── run_vox.py
├── vox_bridge.py
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

## Acknowledgements

[VoxCPMANE](https://github.com/0seba/VoxCPMANE) is the [VOXCPM TTS](https://github.com/OpenBMB/VoxCPM) model with Apple Neural Engine (ANE) backend server.
