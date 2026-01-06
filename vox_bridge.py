import asyncio
import aiohttp
import logging
import os
from contextlib import suppress
from typing import List, Optional

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
# DEFAULTS / CONSTANTS
# -----------------------------
TARGET_RATE = 16000
VERSION = "0.0.5"

AVAILABLE_VOICES = [
    "af_alloy", "af_aoede", "af_bell", "af_heart", "af_jessica", "af_kore",
    "af_nicole", "af_nos", "af_river", "af_sarah", "af_sky", "am_adam",
    "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael", "am_onyx",
    "am_puck", "am_santa", "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis","im_vipin"
]

ATTR = Attribution(name="0seba", url="https://github.com/0seba/VoxCPMANE")

# -----------------------------
# LOGGING
# -----------------------------
_LOGGER = logging.getLogger("vox_bridge")


def _short(s: str, n: int = 140) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "..."


async def wait_for_http_ok(url: str, timeout_s: float = 30.0, interval_s: float = 0.25) -> None:
    """
    Best-effort readiness check. Raises TimeoutError if not reachable within timeout_s.
    """
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_err: Optional[Exception] = None

    async with aiohttp.ClientSession() as session:
        while asyncio.get_event_loop().time() < deadline:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                    if 200 <= resp.status < 500:
                        return
            except Exception as e:
                last_err = e
            await asyncio.sleep(interval_s)

    raise TimeoutError(f"Timed out waiting for HTTP OK at {url}. Last error: {last_err!r}")


class VoxWyomingHandler(AsyncEventHandler):
    def __init__(self, reader, writer, vox_url: str):
        super().__init__(reader, writer)
        self._conn_id = hex(id(self))[-6:]
        self._seq = 0

        # Streaming state
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

        self._vox_url = vox_url

        _LOGGER.info("[conn=%s] handler created vox_url=%s", self._conn_id, self._vox_url)

    def _log_event(self, event: Event):
        self._seq += 1
        _LOGGER.info("[conn=%s seq=%d] WYOMING EVENT TYPE: %s", self._conn_id, self._seq, event.type)

    def _make_voice(self, vid: str) -> TtsVoice:
        return TtsVoice(
            name=vid,
            description=vid,
            languages=["en"],
            installed=True,
            attribution=ATTR,
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

        async with session.post(self._vox_url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
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
                supports_synthesize_streaming=True,
            )])

            _LOGGER.info(
                "[conn=%s] -> Info supports_synthesize_streaming=True voices=%d",
                self._conn_id, len(voices),
            )
            await self.write_event(info.event())
            return True

        # 2) Streaming mode
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

        # 3) Legacy mode
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


class WyomingTTSBridge:
    """
    Minimal bridge wrapper expected by run_vox.py:
      bridge = WyomingTTSBridge(...)
      await bridge.serve()
    """
    def __init__(self, ane_base_url: str, host: str, port: int, name: str = "VoxCPM", language: str = "en"):
        self.ane_base_url = ane_base_url.rstrip("/")
        self.host = host
        self.port = port
        self.name = name
        self.language = language

        # VoxCPMANE server stream endpoint
        self.vox_url = f"{self.ane_base_url}/v1/audio/speech/stream"

    async def serve(self) -> None:
        uri = f"tcp://{self.host}:{self.port}"
        _LOGGER.info("Starting Wyoming server on %s (vox_url=%s)", uri, self.vox_url)
        server = AsyncServer.from_uri(uri)
        await server.run(lambda reader, writer: VoxWyomingHandler(reader, writer, vox_url=self.vox_url))
