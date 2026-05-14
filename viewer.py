#!/usr/bin/env python3
"""Web viewer for the Pub/Sub topics published by zed_pubsub_bridge.py.

Creates ephemeral subscriptions on startup, deletes them on shutdown, and pushes
the latest message per topic to the browser over a WebSocket at ~10 Hz.

Run:
    GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json python3 viewer.py
Open: http://localhost:8080/
"""

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
import uvicorn

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from google.cloud import pubsub_v1


GCP_PROJECT_ID = "yoon-lab"

# Pub/Sub topic IDs — must match the constants in zed_pubsub_bridge.py.
TOPICS = {
    "camera": "zed-camera",
    "pose": "zed-pose",
    "odom": "zed-odom",
}

PUSH_HZ = 10.0
INDEX_HTML = Path(__file__).parent / "index.html"

latest: dict[str, dict | None] = {k: None for k in TOPICS}
delays_ms: dict[str, float | None] = {k: None for k in TOPICS}
_subscriber: pubsub_v1.SubscriberClient | None = None
_futures: dict[str, "pubsub_v1.subscriber.futures.StreamingPullFuture"] = {}
_sub_paths: dict[str, str] = {}


def _make_callback(key: str):
    def _cb(message):
        received_ns = time.time_ns()
        try:
            parsed = json.loads(message.data.decode("utf-8"))
            latest[key] = parsed
            stamp_ns = parsed.get("header", {}).get("stamp_ns")
            if stamp_ns is not None:
                delays_ms[key] = (received_ns - int(stamp_ns)) / 1_000_000
        except Exception:
            latest[key] = {"_raw": message.data[:200].decode("utf-8", "replace")}
        message.ack()
    return _cb


def _start_subscribers() -> None:
    global _subscriber
    _subscriber = pubsub_v1.SubscriberClient()
    publisher = pubsub_v1.PublisherClient()
    suffix = uuid.uuid4().hex[:8]
    for key, topic_id in TOPICS.items():
        topic_path = publisher.topic_path(GCP_PROJECT_ID, topic_id)
        sub_id = f"viewer-{topic_id}-{suffix}"
        sub_path = _subscriber.subscription_path(GCP_PROJECT_ID, sub_id)
        _subscriber.create_subscription(
            request={
                "name": sub_path,
                "topic": topic_path,
                "ack_deadline_seconds": 10,
            }
        )
        _sub_paths[key] = sub_path
        _futures[key] = _subscriber.subscribe(sub_path, callback=_make_callback(key))
        print(f"[viewer] subscribed {key} -> {sub_path}")


def _stop_subscribers() -> None:
    for key, fut in _futures.items():
        try:
            fut.cancel()
        except Exception as e:
            print(f"[viewer] cancel {key} failed: {e}")
    if _subscriber is not None:
        for key, path in _sub_paths.items():
            try:
                _subscriber.delete_subscription(request={"subscription": path})
                print(f"[viewer] deleted {path}")
            except Exception as e:
                print(f"[viewer] delete {path} failed: {e}")
        _subscriber.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _start_subscribers()
    try:
        yield
    finally:
        _stop_subscribers()


app = FastAPI(lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return INDEX_HTML.read_text()


@app.websocket("/ws")
async def ws(sock: WebSocket) -> None:
    await sock.accept()
    period = 1.0 / PUSH_HZ
    try:
        while True:
            payload = dict(latest)
            payload["delays_ms"] = dict(delays_ms)
            await sock.send_text(json.dumps(payload))
            await asyncio.sleep(period)
    except WebSocketDisconnect:
        return


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
