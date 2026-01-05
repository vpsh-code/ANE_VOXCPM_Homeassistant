import asyncio
import aiohttp
import logging
import os
import signal
import subprocess
import sys
import time
from typing import List

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.server import AsyncEventHandler, AsyncServer
from wyoming.tts import (
    Synthesize,
    SynthesizeStart,
    SynthesizeChunk,
    SynthesizeStop,
    SynthesizeStopped,
)
from wyoming.info import Info, TtsProgram, TtsVoice, Describe, Attribution

# -----------------------------
# CONFIG
# -----------------------------
SERVER_PORT = 8080
BRIDGE_PORT = 10331
TARGET_RATE = 16000
VOX_URL = f"http://127.0.0.1:{SERVER_PORT}/v1/audio/speech/stream"
VERSION = "0.0.5"

AVAILABLE_VOICES = [
    "af_alloy", "af_aoede", "af_bell", "af_heart", "af_jessica", "af_kore",
    "af_nicole", "af_nos", "af_river", "af_sarah", "af_sky", "am_adam",
    "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael", "am_onyx",
    "am_puck", "am_santa", "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
]

ATTR = Attribution(name="0seba", url="https://github.com/0seba/VoxCPMANE")

# -----------------------------
# LOGGING
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
_LOGGER = logging.getLogger("vox_bridge")


def _short(s: str, n: int = 140) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "..."


# -----------------------------
# WYOMING HANDLER (FULL DEBUG)
# -----------------------------
class VoxWyomingHandler(AsyncEventHandler):
    def __init__(self, reader, writer):
        super().__init__(reader, writer)
        self._conn_id = hex(id(self))[-6:]
        self._seq = 0

        # Streaming state (Wyoming streaming synthesize)
        self._streaming_active = False
        self._voice_name = "af_sarah"
        self._audio_started = False
        self._text_buf: List[str] = []

        # Counters
        self._legacy_audio_chunks = 0
        self._legacy_audio_bytes = 0
        self._stream_audio_chunks = 0
        self._stream_audio_bytes = 0
        self._stream_flushes = 0

        _LOGGER.info("[conn=%s] handler created", self._conn_id)

    def _log_event(self, event: Event):
        self._seq += 1
        _LOGGER.info("[conn=%s seq=%d] WYOMING EVENT TYPE: %s", self._conn_id, self._seq, event.type)

    def _make_voice(self, name: str) -> TtsVoice:
        return TtsVoice(
            name=name,
            languages=["en"],
            installed=True,
            attribution=ATTR,
            description="VoxCPM",
            version=VERSION,
        )

    async def _ensure_audio_start(self):
        if not self._audio_started:
            _LOGGER.info("[conn=%s] -> AudioStart(rate=%s)", self._conn_id, TARGET_RATE)
            await self.write_event(AudioStart(rate=TARGET_RATE, width=2, channels=1).event())
            self._audio_started = True

    def _flush_ready(self, text: str) -> bool:
        t = text.rstrip()
        if not t:
            return False
        if len(t) >= 300:
            return True
        return t.endswith((".", "!", "?", "\n"))

    async def _stream_vox_pcm(self, session: aiohttp.ClientSession, text: str, voice: str, mode: str):
        payload = {
            "input": text,
            "model": "voxcpm",
            "voice": voice,
            "response_format": "pcm",
        }

        _LOGGER.info(
            "[conn=%s mode=%s] POST Vox stream voice=%s text=%r",
            self._conn_id, mode, voice, _short(text),
        )

        async with session.post(VOX_URL, json=payload, timeout=120) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Vox server HTTP {resp.status}: {body[:200]}")

            async for chunk in resp.content.iter_chunked(1024):
                if not chunk:
                    continue

                if mode == "legacy":
                    self._legacy_audio_chunks += 1
                    self._legacy_audio_bytes += len(chunk)
                else:
                    self._stream_audio_chunks += 1
                    self._stream_audio_bytes += len(chunk)

                await self.write_event(AudioChunk(audio=chunk, rate=TARGET_RATE, width=2, channels=1).event())
                await asyncio.sleep(0)

        _LOGGER.info(
            "[conn=%s mode=%s] Vox done chunks=%d bytes=%d",
            self._conn_id, mode,
            (self._legacy_audio_chunks if mode == "legacy" else self._stream_audio_chunks),
            (self._legacy_audio_bytes if mode == "legacy" else self._stream_audio_bytes),
        )

    async def _flush_text(self, session: aiohttp.ClientSession, force: bool):
        if not self._text_buf:
            return

        text = "".join(self._text_buf)
        if (not force) and (not self._flush_ready(text)):
            _LOGGER.info("[conn=%s stream] buffer not ready len=%d tail=%r", self._conn_id, len(text), _short(text, 80))
            return

        self._text_buf = []
        self._stream_flushes += 1

        _LOGGER.info("[conn=%s stream] FLUSH #%d force=%s len=%d", self._conn_id, self._stream_flushes, force, len(text))
        await self._ensure_audio_start()
        await self._stream_vox_pcm(session=session, text=text, voice=self._voice_name, mode="stream")

    async def handle_event(self, event: Event) -> bool:
        self._log_event(event)

        # 1) Discovery: advertise streaming support
        if Describe.is_type(event.type):
            voices = [self._make_voice(v) for v in AVAILABLE_VOICES]
            info = Info(tts=[TtsProgram(
                name="voxcpmane",
                description="VoxCPM ANE TTS",
                installed=True,
                voices=voices,
                version=VERSION,
                attribution=ATTR,
                supports_synthesize_streaming=True,  # key capability flag
            )])

            _LOGGER.info(
                "[conn=%s] -> Info supports_synthesize_streaming=True voices=%d",
                self._conn_id, len(voices),
            )
            await self.write_event(info.event())
            return True

        # 2) Streaming mode (what HA *should* do if it uses streaming TTS)
        if SynthesizeStart.is_type(event.type):
            start = SynthesizeStart.from_event(event)
            self._streaming_active = True
            self._audio_started = False
            self._text_buf = []
            self._stream_audio_chunks = 0
            self._stream_audio_bytes = 0
            self._stream_flushes = 0

            self._voice_name = start.voice.name if (start.voice and start.voice.name) else "af_sarah"
            _LOGGER.info("[conn=%s] STREAM START voice=%s", self._conn_id, self._voice_name)

            # Optional echo
            await self.write_event(SynthesizeStart(voice=self._make_voice(self._voice_name)).event())
            return True

        if SynthesizeChunk.is_type(event.type):
            ch = SynthesizeChunk.from_event(event)
            self._text_buf.append(ch.text)
            _LOGGER.info("[conn=%s stream] got chunk len=%d text=%r", self._conn_id, len(ch.text), _short(ch.text, 80))

            async with aiohttp.ClientSession() as session:
                await self._flush_text(session=session, force=False)
            return True

        if SynthesizeStop.is_type(event.type):
            _LOGGER.info("[conn=%s] STREAM STOP -> flush + AudioStop + SynthesizeStopped", self._conn_id)
            async with aiohttp.ClientSession() as session:
                await self._flush_text(session=session, force=True)

            if self._audio_started:
                await self.write_event(AudioStop().event())

            await self.write_event(SynthesizeStopped().event())

            _LOGGER.info(
                "[conn=%s] STREAM DONE flushes=%d chunks=%d bytes=%d",
                self._conn_id, self._stream_flushes, self._stream_audio_chunks, self._stream_audio_bytes,
            )

            self._streaming_active = False
            self._audio_started = False
            self._text_buf = []
            return True

        # 3) Legacy mode (what your current logs prove HA is doing)
        if Synthesize.is_type(event.type):
            if self._streaming_active:
                _LOGGER.info("[conn=%s] legacy Synthesize received while streaming_active=True -> ignoring", self._conn_id)
                return True

            synth = Synthesize.from_event(event)
            voice = synth.voice.name if (synth.voice and synth.voice.name) else "af_sarah"

            self._legacy_audio_chunks = 0
            self._legacy_audio_bytes = 0
            self._audio_started = False

            _LOGGER.info("[conn=%s] LEGACY synthesize voice=%s text=%r", self._conn_id, voice, _short(synth.text))

            await self.write_event(SynthesizeStart(voice=self._make_voice(voice)).event())
            await self._ensure_audio_start()

            async with aiohttp.ClientSession() as session:
                await self._stream_vox_pcm(session=session, text=synth.text, voice=voice, mode="legacy")

            await self.write_event(AudioStop().event())

            _LOGGER.info("[conn=%s] LEGACY DONE chunks=%d bytes=%d", self._conn_id, self._legacy_audio_chunks, self._legacy_audio_bytes)
            return True

        _LOGGER.info("[conn=%s] unhandled event=%s", self._conn_id, event.type)
        return True


# -----------------------------
# RUNNER (starts Vox server + Wyoming bridge)
# -----------------------------
def kill_processes_on_ports(ports):
    for port in ports:
        try:
            pids = subprocess.check_output(["lsof", "-t", f"-i:{port}"]).decode().split()
            for pid in pids:
                os.kill(int(pid), signal.SIGKILL)
        except Exception:
            pass


async def start_bridge():
    server = AsyncServer.from_uri(f"tcp://0.0.0.0:{BRIDGE_PORT}")
    await server.run(lambda reader, writer: VoxWyomingHandler(reader, writer))


def main():
    print("🧹 Cleaning up ports...")
    kill_processes_on_ports([SERVER_PORT, BRIDGE_PORT])
    time.sleep(1)

    print(f"🚀 Starting ANE Server on port {SERVER_PORT}...")
    server_proc = subprocess.Popen([
        sys.executable, "-m", "voxcpmane.server", "--port", str(SERVER_PORT), "--host", "127.0.0.1"
    ])

    print("⏳ Waiting for ANE Server to initialize (30s)...")
    time.sleep(30)

    if server_proc.poll() is not None:
        print("❌ ANE Server failed to start.")
        sys.exit(1)

    print(f"🌉 Starting Wyoming Bridge on port {BRIDGE_PORT}...")
    try:
        asyncio.run(start_bridge())
    except KeyboardInterrupt:
        print("\n🛑 Stopping...")
    finally:
        server_proc.terminate()
        kill_processes_on_ports([SERVER_PORT, BRIDGE_PORT])


if __name__ == "__main__":
    main()
