import asyncio
import aiohttp
import logging
from wyoming.tts import Synthesize
from wyoming.info import Info, TtsProgram, TtsVoice, Describe
from wyoming.server import AsyncTcpServer, AsyncEventHandler
from wyoming.audio import AudioStart, AudioChunk, AudioStop

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger("vox_bridge")

VOX_URL = "http://localhost:8000/v1/audio/speech/stream"

AVAILABLE_VOICES = [
    'af_alloy', 'af_aoede', 'af_bell', 'af_heart', 'af_jessic', 'af_kore', 
    'af_nicole', 'af_no', 'af_river', 'af_sarah', 'af_sky', 'am_adam', 
    'am_echo', 'am_eric', 'am_fenrir', 'am_liam', 'am_michael', 'am_onyx', 
    'am_puck', 'am_sant', 'bf_alice', 'bf_emm', 'bf_isabell', 'bf_lily', 
    'bm_daniel', 'bm_fable', 'bm_george', 'bm_lewis'
]

class VoxWyomingHandler(AsyncEventHandler):
    async def handle_event(self, event):
        if Describe.is_type(event.type):
            _LOGGER.info("Sending 28 voices to Home Assistant")
            wyoming_voices = [
                TtsVoice(
                    name=v,
                    description=f"VoxCPM Voice: {v}",
                    languages=["en"],
                    attribution={"name": "0seba", "url": "https://github.com/0seba/VoxCPMANE"},
                    version="0.0.5",
                    installed=True
                ) for v in AVAILABLE_VOICES
            ]

            info = Info(
                tts=[
                    TtsProgram(
                        name="voxcpmane",
                        description="VoxCPM Apple Neural Engine TTS",
                        attribution={"name": "0seba", "url": "https://github.com/0seba/VoxCPMANE"},
                        installed=True,
                        version="0.0.5",
                        voices=wyoming_voices,
                    )
                ]
            )
            await self.write_event(info.event())
            return True

        if Synthesize.is_type(event.type):
            synth = Synthesize.from_event(event)
            voice_to_use = synth.voice.name if synth.voice else "af_sarah"
            _LOGGER.info(f"Streaming synthesis: {synth.text[:30]}... using {voice_to_use}")
            await self.process_tts_stream(synth.text, voice_to_use)
            return False 

        return True

    async def process_tts_stream(self, text, voice):
        payload = {
            "input": text,
            "model": "voxcpm",
            "voice": voice,
            "response_format": "pcm"
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(VOX_URL, json=payload, timeout=120) as resp:
                    if resp.status == 200:
                        rate, width, channels = 16000, 2, 1
                        await self.write_event(AudioStart(rate=rate, width=width, channels=channels).event())
                        
                        async for chunk in resp.content.iter_chunked(1024):
                            if chunk:
                                await self.write_event(AudioChunk(
                                    audio=chunk, rate=rate, width=width, channels=channels
                                ).event())
                        
                        await self.write_event(AudioStop().event())
                        _LOGGER.info("Streaming complete.")
                    else:
                        _LOGGER.error(f"Server error {resp.status}")
            except Exception as e:
                _LOGGER.error(f"Streaming error: {e}")

async def main():
    server = AsyncTcpServer("0.0.0.0", 10330)
    _LOGGER.info("Vox Bridge active on port 10330")
    await server.run(VoxWyomingHandler)

if __name__ == "__main__":
    asyncio.run(main())
