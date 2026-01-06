#!/usr/bin/env python3
import asyncio
import logging
import os
from contextlib import suppress

import uvicorn

LOG = logging.getLogger("run_vox")


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if not v:
        return default
    return int(v)


def _env_str(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v else default


async def _serve_ane(app, host: str, port: int) -> None:
    cfg = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True,
        loop="asyncio",
    )
    server = uvicorn.Server(cfg)
    await server.serve()


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler("vox_server.log"),
            logging.StreamHandler()
        ]
    )

    ane_host = _env_str("ANE_HOST", "127.0.0.1")
    ane_port = _env_int("ANE_PORT", 8080)

    wyoming_host = _env_str("WYOMING_HOST", "0.0.0.0")
    wyoming_port = _env_int("WYOMING_PORT", 10333)
    wyoming_name = _env_str("WYOMING_NAME", "VoxCPM")
    wyoming_lang = _env_str("WYOMING_LANGUAGE", "en")

    LOG.info("Starting ANE server on %s:%s ...", ane_host, ane_port)
    from voxcpmane.server import app as ane_app  # type: ignore

    ane_task = asyncio.create_task(_serve_ane(ane_app, ane_host, ane_port))

    # Wait until ANE HTTP is reachable (best-effort, does not block forever)
    from vox_bridge import wait_for_http_ok, WyomingTTSBridge

    await wait_for_http_ok(f"http://{ane_host}:{ane_port}", timeout_s=30.0)

    LOG.info("Starting Wyoming bridge on %s:%s ...", wyoming_host, wyoming_port)
    bridge = WyomingTTSBridge(
        ane_base_url=f"http://{ane_host}:{ane_port}",
        host=wyoming_host,
        port=wyoming_port,
        name=wyoming_name,
        language=wyoming_lang,
    )

    bridge_task = asyncio.create_task(bridge.serve())

    done, pending = await asyncio.wait(
        {ane_task, bridge_task},
        return_when=asyncio.FIRST_EXCEPTION,
    )

    # If one task failed, stop the other cleanly.
    for t in done:
        with suppress(Exception):
            t.result()

    for t in pending:
        t.cancel()
        with suppress(Exception):
            await t

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))