# run_vox.py
#!/usr/bin/env python3
from pathlib import Path
import asyncio
import logging
import os
import time
import warnings
from contextlib import suppress

import uvicorn

LOG = logging.getLogger("run_vox")

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)


def setup_voices_interactive(voices_root: Path) -> None:
    """
    Checks for:
      ~/.cache/ane_tts/voices/<voice>/<voice>.wav
      ~/.cache/ane_tts/voices/<voice>/<voice>.txt
    Generates only missing ones.
    """
    voice_map = {
        "a": [
            "af_bella", "af_heart", "af_jessica", "af_kore", "af_nicole", "af_nova",
            "af_river", "af_sarah", "af_sky",
            "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael",
            "am_onyx", "am_puck", "am_santa",
        ],
        "b": [
            "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
            "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
        ],
    }

    prompt_text = "The quick brown fox jumps over the lazy dog."

    missing = []
    voice_to_lang = {}
    for lang, voices in voice_map.items():
        for v in voices:
            voice_to_lang[v] = lang
            v_dir = voices_root / v
            wav = v_dir / f"{v}.wav"
            txt = v_dir / f"{v}.txt"
            if not wav.exists() or not txt.exists():
                missing.append(v)

    if not missing:
        LOG.info("All standard Kokoro voices are present (wav+txt).")
        return

    print("\n" + "=" * 50)
    print(f"KOKORO VOICE CHECK: {len(missing)} voices missing.")
    print(f"Target: {voices_root}")
    print("=" * 50)
    choice = input(f"Would you like to generate the missing {len(missing)} voices now? (y/N): ").lower().strip()
    if choice != "y":
        return

    import soundfile as sf
    from kokoro import KPipeline
    from tqdm import tqdm

    voices_root.mkdir(parents=True, exist_ok=True)
    pipes = {}

    with tqdm(total=len(missing), desc="Generating Missing Voices", unit="voice") as pbar:
        for v in missing:
            lang = voice_to_lang[v]
            if lang not in pipes:
                pipes[lang] = KPipeline(repo_id="hexgrad/Kokoro-82M", lang_code=lang)

            pipe = pipes[lang]
            v_dir = voices_root / v
            v_dir.mkdir(parents=True, exist_ok=True)

            wav_path = v_dir / f"{v}.wav"
            txt_path = v_dir / f"{v}.txt"

            gen = pipe(prompt_text, voice=v)
            for _, _, audio in gen:
                sf.write(str(wav_path), audio, 24000)
                break

            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(prompt_text)

            pbar.update(1)
            time.sleep(0.05)

    print("\n✅ Generation complete! Proceeding to start server...")


async def _serve_ane(app, host: str, port: int) -> None:
    cfg = uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False)
    await uvicorn.Server(cfg).serve()


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    voices_root = Path.home() / ".cache" / "ane_tts" / "voices"
    setup_voices_interactive(voices_root)

    from voxcpmane.server import app as ane_app
    from vox_bridge import wait_for_http_ok, WyomingTTSBridge

    LOG.info("Starting ANE server...")
    asyncio.create_task(_serve_ane(ane_app, "127.0.0.1", 8080))
    await wait_for_http_ok("http://127.0.0.1:8080")

    host = os.getenv("WYOMING_HOST", "0.0.0.0")
    port = int(os.getenv("WYOMING_PORT", "10333"))

    LOG.info("Starting Wyoming bridge on %s:%s ...", host, port)
    bridge = WyomingTTSBridge(
        ane_base_url="http://127.0.0.1:8080",
        host=host,
        port=port,
    )
    await bridge.serve()
    return 0


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        raise SystemExit(asyncio.run(main()))

