import asyncio
import aiohttp
import logging
import time
from typing import List, Optional

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.server import AsyncEventHandler, AsyncServer
from wyoming.info import Info, TtsProgram, TtsVoice, Describe, Attribution
from wyoming.tts import (
    Synthesize,
    SynthesizeStart,
    SynthesizeChunk,
    SynthesizeStop,
    SynthesizeStopped,
)

# -----------------------------
# CONFIG
# -----------------------------
VOX_URL = "http://127.0.0.1:8080/v1/audio/speech/stream"
BRIDGE_PORT = 10331
TARGET_RATE = 16000
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


def _now_ms() -> int:
    return int(time.time() * 1000)


def _short(s: str, n: int = 120) -> str:
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "..."


# -----------------------------
# WYOMING HANDLER
# -----------------------------
class VoxWyomingHandler(AsyncEventHandler):
    """
    Proof-oriented implementation:
      - Advertises supports_synthesize_streaming=True
      - Logs all inbound event types and key details
      - Handles both streaming (start/chunk/stop) and legacy (synthesize)
      - Streams PCM from Vox endpoint as AudioChunk events
    """

    def __init__(self, reader, writer):
        super().__init__(reader, writer)

        # Per-connection state
        self._streaming_active: bool = False
        self._voice_name: str = "af_sarah"
        self._audio_started: bool = False
        self._text_buf: List[str] = []

        # Debug counters
        self._conn_id = hex(id(self))[-6:]
        self._event_seq = 0

        self._legacy_audio_chunks = 0
        self._legacy_audio_bytes = 0

        self._stream_audio_chunks = 0
        self._stream_audio_bytes = 0
        self._stream_flushes = 0

        _LOGGER.info("[conn=%s] handler created", self._conn_id)

    # ---------- Debug helpers ----------

    def _log_event(self, event: Event):
        self._event_seq += 1
        # event.type is what matters to prove whether HA uses streaming types
        _LOGGER.info(
            "[conn=%s seq=%d] WYOMING EVENT TYPE: %s",
            self._conn_id,
            self._event_seq,
            event.type,
        )

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
        # flush heuristic
        if len(t) >= 300:
            return True
        return t.endswith((".", "!", "?", "\n"))

    async def _stream_vox_pcm(self, session: aiohttp.ClientSession, text: str, voice: str, mode: str):
        """
        mode is 'legacy' or 'stream' for counters/logging only.
        """
        payload = {
            "input": text,
            "model": "voxcpm",
            "voice": voice,
            "response_format": "pcm",
        }

        start_ms = _now_ms()
        _LOGGER.info(
            "[conn=%s mode=%s] POST Vox stream: voice=%s text=%r",
            self._conn_id,
            mode,
            voice,
            _short(text, 140),
        )

        async with session.post(VOX_URL, json=payload, timeout=120) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Vox server HTTP {resp.status}: {body[:200]}")

            # iterate the HTTP response stream
            async for chunk in resp.content.iter_chunked(1024):
                if not chunk:
                    continue

                if mode == "legacy":
                    self._legacy_audio_chunks += 1
                    self._legacy_audio_bytes += len(chunk)
                else:
                    self._stream_audio_chunks += 1
                    self._stream_audio_bytes += len(chunk)

                await self.write_event(
                    AudioChunk(audio=chunk, rate=TARGET_RATE, width=2, channels=1).event()
                )
                await asyncio.sleep(0)

        dur_ms = _now_ms() - start_ms
        _LOGGER.info(
            "[conn=%s mode=%s] Vox stream done in %dms (chunks=%d bytes=%d)",
            self._conn_id,
            mode,
            dur_ms,
            (self._legacy_audio_chunks if mode == "legacy" else self._stream_audio_chunks),
            (self._legacy_audio_bytes if mode == "legacy" else self._stream_audio_bytes),
        )

    async def _flush_text(self, session: aiohttp.ClientSession, force: bool):
        if not self._text_buf:
            return

        text = "".join(self._text_buf)
        if (not force) and (not self._flush_ready(text)):
            _LOGGER.info(
                "[conn=%s stream] buffer not ready (len=%d) text=%r",
                self._conn_id,
                len(text),
                _short(text, 120),
            )
            return

        self._text_buf = []
        self._stream_flushes += 1

        _LOGGER.info(
            "[conn=%s stream] FLUSH #%d force=%s len=%d text=%r",
            self._conn_id,
            self._stream_flushes,
            force,
            len(text),
            _short(text, 160),
        )

        await self._ensure_audio_start()
        await self._stream_vox_pcm(session=session, text=text, voice=self._voice_name, mode="stream")

    # ---------- Main handler ----------

    async def handle_event(self, event: Event) -> bool:
        self._log_event(event)

        # A) Describe handshake: what we advertise (this is key proof)
        if Describe.is_type(event.type):
            wyoming_voices = [self._make_voice(v) for v in AVAILABLE_VOICES]

            info = Info(
                tts=[
                    TtsProgram(
                        name="voxcpmane",
                        description="VoxCPM ANE TTS",
                        installed=True,
                        voices=wyoming_voices,
                        version=VERSION,
                        attribution=ATTR,
                        supports_synthesize_streaming=True,
                    )
                ]
            )

            _LOGGER.info(
                "[conn=%s] sending Info(tts[0].supports_synthesize_streaming=True, voices=%d)",
                self._conn_id,
                len(wyoming_voices),
            )
            await self.write_event(info.event())
            return True

        # B) Streaming start
        if SynthesizeStart.is_type(event.type):
            start = SynthesizeStart.from_event(event)

            self._streaming_active = True
            self._audio_started = False
            self._text_buf = []
            self._stream_audio_chunks = 0
            self._stream_audio_bytes = 0
            self._stream_flushes = 0

            if start.voice and start.voice.name:
                self._voice_name = start.voice.name
            else:
                self._voice_name = "af_sarah"

            _LOGGER.info(
                "[conn=%s] STREAM MODE START voice=%s",
                self._conn_id,
                self._voice_name,
            )

            # Echo a start back (optional)
            await self.write_event(SynthesizeStart(voice=self._make_voice(self._voice_name)).event())
            return True

        # C) Streaming chunk
        if SynthesizeChunk.is_type(event.type):
            chunk = SynthesizeChunk.from_event(event)
            self._text_buf.append(chunk.text)

            current = "".join(self._text_buf)
            _LOGGER.info(
                "[conn=%s stream] got chunk len=%d buf_len=%d text=%r",
                self._conn_id,
                len(chunk.text),
                len(current),
                _short(chunk.text, 80),
            )

            async with aiohttp.ClientSession() as session:
                await self._flush_text(session=session, force=False)

            return True

        # D) Streaming stop
        if SynthesizeStop.is_type(event.type):
            _LOGGER.info("[conn=%s] STREAM MODE STOP -> final flush + AudioStop + SynthesizeStopped", self._conn_id)

            async with aiohttp.ClientSession() as session:
                await self._flush_text(session=session, force=True)

            if self._audio_started:
                await self.write_event(AudioStop().event())

            await self.write_event(SynthesizeStopped().event())

            _LOGGER.info(
                "[conn=%s] STREAM DONE (flushes=%d audio_chunks=%d audio_bytes=%d)",
                self._conn_id,
                self._stream_flushes,
                self._stream_audio_chunks,
                self._stream_audio_bytes,
            )

            self._streaming_active = False
            self._audio_started = False
            self._text_buf = []
            return True

        # E) Legacy synthesize (single-shot)
        if Synthesize.is_type(event.type):
            # If HA is in streaming flow, ignore legacy events
            if self._streaming_active:
                _LOGGER.info("[conn=%s] legacy Synthesize received while streaming_active=True -> ignoring", self._conn_id)
                return True

            synth = Synthesize.from_event(event)
            voice = synth.voice.name if (synth.voice and synth.voice.name) else "af_sarah"

            self._legacy_audio_chunks = 0
            self._legacy_audio_bytes = 0
            self._audio_started = False

            _LOGGER.info(
                "[conn=%s] LEGACY MODE synthesize voice=%s text=%r",
                self._conn_id,
                voice,
                _short(synth.text, 180),
            )

            # Start markers
            await self.write_event(SynthesizeStart(voice=self._make_voice(voice)).event())
            await self._ensure_audio_start()

            # Vox streaming PCM
            async with aiohttp.ClientSession() as session:
                await self._stream_vox_pcm(session=session, text=synth.text, voice=voice, mode="legacy")

            await self.write_event(AudioStop().event())

            _LOGGER.info(
                "[conn=%s] LEGACY DONE (audio_chunks=%d audio_bytes=%d)",
                self._conn_id,
                self._legacy_audio_chunks,
                self._legacy_audio_bytes,
            )
            return True

        # F) Unhandled event types (log only)
        _LOGGER.info("[conn=%s] unhandled event type=%s", self._conn_id, event.type)
        return True


async def main():
    _LOGGER.info("Vox Wyoming Bridge listening on tcp://0.0.0.0:%s", BRIDGE_PORT)
    server = AsyncServer.from_uri(f"tcp://0.0.0.0:{BRIDGE_PORT}")
    await server.run(lambda reader, writer: VoxWyomingHandler(reader, writer))


if __name__ == "__main__":
    asyncio.run(main())
