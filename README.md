# VoxCPMANE Wyoming Bridge

This project bridges the [VoxCPMANE](https://github.com/0seba/VoxCPMANE) (Apple Neural Engine TTS) to [Home Assistant](https://www.home-assistant.io/) using the **Wyoming protocol**. 

By leveraging the **Apple Neural Engine (ANE)**, this bridge allows for lightning-fast, 100% local, high-quality speech generation on Apple Silicon Macs.

## Prerequisites

* **Hardware:** An Apple Silicon Mac (M1, M2, M3, or M4).
* **Software:** Python 3.11 or higher.
* **Package Manager:** `uv` (recommended) or `pip`.

## Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/vpsh-code/ANE_VOXCPM_Homeassistant.git
    cd voxcpmane-wyoming
    ```

2.  **Install dependencies:**
    If using `uv`:
    ```bash
    uv pip install voxcpmane wyoming aiohttp
    ```
    If using standard `pip`:
    ```bash
    pip install voxcpmane wyoming aiohttp
    ```

## Usage

1.  **Start the service:**
    ```bash
    python3 run_vox.py
    ```
    This launcher will automatically start both the **VoxCPM server** (port 8000) and the **Wyoming bridge** (port 10330).

2.  **Add to Home Assistant:**
    * Navigate to **Settings** > **Devices & Services**.
    * Click **Add Integration** and search for **Wyoming**.
    * Enter your Mac's **IP Address** and port **10330**.

## Features

* **High Performance:** Uses the dedicated Apple Neural Engine for inference.
* **Streaming Support:** Audio starts playing in Home Assistant almost instantly.
* **28 High-Quality Voices:** Choose from a wide variety of male and female voices directly in the Home Assistant UI.

---
*Note: Ensure your Mac and Home Assistant instance are on the same network.*
