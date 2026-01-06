# vox_bridge.py
import asyncio
import aiohttp
import logging
import os
import time
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
VERSION = "0.2.0"

AVAILABLE_VOICES = [
    "af_alloy", "af_aoede", "af_bell", "af_heart", "af_jessica", "af_kore",
    "af_nicole", "af_nos", "af_river", "af_sarah", "af_sky", "am_adam",
    "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael", "am_onyx",
    "am_puck", "am_santa", "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis"
]

ATTR = Attribution(name="0seba", url="https://github.com/0seba/VoxCPMANE")

_LOGGER = logging.getLogger("vox_bridge")

def _short(s: str, n: int = 140) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "..."

async def wait_for_http_ok(url: str, timeout_s: float = 30.0, interval_s: float = 0.25) -> None:
    deadline = asyncio.get_event_loop().time() + timeout_s
    async with aiohttp.ClientSession() as session:
        while asyncio.get_event_loop().time() < deadline:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                    if 200 <= resp.status < 500:
                        return
            except Exception:
                pass
            await asyncio.sleep(interval_s)
    raise TimeoutError(f"Timed out waiting for HTTP OK at {url}")

class VoxWyomingHandler(AsyncEventHandler):
    def __init__(self, reader, writer, vox_url: str):
        super().__init__(reader, writer)
        self._conn_id = hex(id(self))[-6:]
        self._streaming_active = False
        self._voice_name = "af_sarah"
        self._audio_started = False
        self._text_buf: List[str] = []
        self._vox_url = vox_url

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
            await self.write_event(AudioStart(rate=TARGET_RATE, width=2, channels=1).event())
            self._audio_started = True

    def _flush_ready(self, text: str) -> bool:
        t = text.rstrip()
        if not t: return False
        if len(t) >= 300: return True
        return t.endswith((".", "!", "?", "\n"))

    async def _stream_vox_pcm(self, session: aiohttp.ClientSession, text: str, voice: str, mode: str):
        payload = {
            "input": text,
            "model": "voxcpm",
            "voice": voice,
            "response_format": "pcm",
        }

        _LOGGER.info("[conn=%s] TTS (%s): %r", self._conn_id, mode, _short(text))
        start_time = time.perf_counter()
        first_chunk = False

        async with session.post(self._vox_url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Vox server error {resp.status}: {body[:100]}")

            async for chunk in resp.content.iter_chunked(1024):
                if not chunk: continue
                if not first_chunk:
                    _LOGGER.debug("[conn=%s] TTFT: %.4fs", self._conn_id, time.perf_counter() - start_time)
                    first_chunk = True
                await self.write_event(AudioChunk(audio=chunk, rate=TARGET_RATE, width=2, channels=1).event())

    async def _flush_text(self, session: aiohttp.ClientSession, force: bool):
        if not self._text_buf: return
        text = "".join(self._text_buf)
        if (not force) and (not self._flush_ready(text)):
            return
        self._text_buf = []
        await self._ensure_audio_start()
        await self._stream_vox_pcm(session=session, text=text, voice=self._voice_name, mode="stream")

    async def handle_event(self, event: Event) -> bool:
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
            await self.write_event(info.event())
            return True

        if SynthesizeStart.is_type(event.type):
            start = SynthesizeStart.from_event(event)
            self._streaming_active = True
            self._audio_started = False
            self._text_buf = []
            self._voice_name = start.voice.name if (start.voice and start.voice.name) else "af_sarah"
            await self.write_event(SynthesizeStart(voice=self._make_voice(self._voice_name)).event())
            return True

        if SynthesizeChunk.is_type(event.type):
            ch = SynthesizeChunk.from_event(event)
            self._text_buf.append(ch.text)
            async with aiohttp.ClientSession() as session:
                await self._flush_text(session=session, force=False)
            return True

        if SynthesizeStop.is_type(event.type):
            async with aiohttp.ClientSession() as session:
                await self._flush_text(session=session, force=True)
            if self._audio_started:
                await self.write_event(AudioStop().event())
            await self.write_event(SynthesizeStopped().event())
            self._streaming_active = False
            return True

        if Synthesize.is_type(event.type):
            if self._streaming_active: return True
            synth = Synthesize.from_event(event)
            voice = synth.voice.name if (synth.voice and synth.voice.name) else "af_sarah"
            await self.write_event(SynthesizeStart(voice=self._make_voice(voice)).event())
            await self._ensure_audio_start()
            async with aiohttp.ClientSession() as session:
                await self._stream_vox_pcm(session=session, text=synth.text, voice=voice, mode="legacy")
            await self.write_event(AudioStop().event())
            await self.write_event(SynthesizeStopped().event())
            return True

        return True

class WyomingTTSBridge:
    def __init__(self, ane_base_url: str, host: str, port: int):
        self.vox_url = f"{ane_base_url.rstrip('/')}/v1/audio/speech/stream"
        self.host = host
        self.port = port

    async def serve(self) -> None:
        server = AsyncServer.from_uri(f"tcp://{self.host}:{self.port}")
        _LOGGER.info("Wyoming bridge listening on %s:%s", self.host, self.port)
        await server.run(lambda reader, writer: VoxWyomingHandler(reader, writer, vox_url=self.vox_url))
