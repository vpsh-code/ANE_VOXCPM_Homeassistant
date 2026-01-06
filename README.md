# VoxCPMANE Wyoming Bridge

This project bridges VoxCPMANE (Apple Neural Engine TTS) with Home Assistant using the Wyoming protocol.

By leveraging the Apple Neural Engine (ANE), the bridge enables fully local, low-latency, and high-quality text-to-speech on Apple Silicon Macs (M1, M2, M3, M4).

Tested on Macbook Pro M3 with macOS Sequoia/Tahoe.

## Overview

- **ANE-Powered**: Optimized for Apple Silicon hardware acceleration.
- **Interactive Setup**: Automatically detects and offers to generate missing standard Kokoro voices on the first launch.
- **Wyoming Ready**: Seamless integration with Home Assistant's Voice Assistant (Assist).
- **Zero Cloud**: 100% local inference for privacy and speed.

## Prerequisites

### Hardware
- Apple Silicon Mac (M1, M2, M3, M4)

### Software
- Python 3.11+
- uv package manager (strongly recommended)

## Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/vpsh-code/ANE_VOXCPM_Homeassistant.git
cd ANE_VOXCPM_Homeassistant
uv sync
source .venv/bin/activate
```

## Usage

### Option 1: Manual Start (Foreground)

Best for the first run. The script will check for standard voices in `~/.cache/ane_tts/voices` and prompt you to generate them if they are missing.

```bash
uv run run_vox.py
```

- ANE Server: Internal on `127.0.0.1:8080`
- Wyoming Bridge: External on `0.0.0.0:10333`

### Option 2: Background (Current Session)

```bash
nohup uv run run_vox.py > vox.log 2>&1 &
```

### Option 3: Persistent macOS Service

To ensure the bridge starts automatically when you log in:

#### 1. Create the LaunchAgent

Run this command from the project root:

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

#### 2. Load the Service

```bash
cp com.voxcpmane.bridge.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.voxcpmane.bridge.plist
```

## Home Assistant Integration

### 1. Identify Mac IP

```bash
ipconfig getifaddr en0
```

### 2. Configure Wyoming

In Home Assistant: **Settings → Devices & Services → Add Integration**.

- Search for **Wyoming**
- Host: Your Mac's IP address
- Port: `10333`

### 3. Adding Custom Cloned Voices

The code looks for voices in:

```
~/.cache/ane_tts/voices/<voice_name>/
```

Steps:
1. Place `<voice_name>.wav` and `<voice_name>.txt` inside a folder named after the voice.
2. Open `vox_bridge.py` and add your voice name to the `AVAILABLE_VOICES` list.
3. Restart the bridge.
4. Reload the Wyoming integration in Home Assistant and select the new voice.

**Note**: Do not clone a voice of someone without their explicit permission.

## Features

- **Automated Voice Generation**: Uses Kokoro-82M to bootstrap your local voice library.
- **Streaming Support**: Audio begins playing as it is generated, minimizing perceived latency.
- **Enhanced Logging**: Logs both to the console and `vox_server.log` for troubleshooting.

## Repository Structure

```
ANE_VOXCPM_Homeassistant/
├── run_vox.py        # Main entry, manages ANE server & Wyoming bridge
├── vox_bridge.py     # Wyoming protocol & event handling
├── pyproject.toml    # Project metadata & dependencies
├── uv.lock           # Dependency lockfile
└── README.md         # Documentation
```

## Acknowledgements

Special thanks to **0seba** for the ANE-optimized server and the **VoxCPM / Kokoro** teams.
