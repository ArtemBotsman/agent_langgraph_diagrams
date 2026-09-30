"""Opt-in HTTP delivery fix; historical experiment gateways remain unchanged.

Send SSE headers/comments while the unchanged, budgeted provider call is pending.
Reconnects with exactly the same JSON request share its outcome within this run:
they cannot start a second billed request. No failed provider call is retried.
This transport policy must be disclosed in any new experimental protocol.
"""

import hashlib
import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jury_stage41_gateway import CacheAwareGateway


class DeliveryGateway(CacheAwareGateway):
    def __init__(self, *args, heartbeat_interval=5.0, **kwargs):
        if not math.isfinite(heartbeat_interval) or heartbeat_interval <= 0:
            raise ValueError("Heartbeat interval must be positive")
        super().__init__(*args, **kwargs)
        # Retain the original cache-aware call/accounting implementation, but
        # replace its buffered HTTP endpoint. No historical source is patched.
        super().close()
        self.delivery_lock = threading.Lock()
        self.close_lock = threading.Lock()
        self.closing = False
        self.delivery_events = []
        self.futures = {}
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="budgeted-delivery")
        self.heartbeat_interval = heartbeat_interval
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                if (
                    self.path != "/v1/chat/completions"
                    or self.headers.get("Authorization") != "Bearer " + owner.token
                ):
                    self.send_error(403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length < 2_000_000:
                        self.send_error(413)
                        return
                    body = self.rfile.read(length)
                    if len(body) != length:
                        raise ValueError("Incomplete request body")
                    original = json.loads(body)
                    future, key = owner.submit_once(original)
                except (ValueError, UnicodeError):
                    self.send_error(400)
                    return
                except RuntimeError:
                    self.send_error(503)
                    return
                stream = bool(original.get("stream"))
                try:
                    if stream:
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        self.wfile.write(b": budgeted upstream request pending\n\n")
                        self.wfile.flush()
                        while True:
                            try:
                                raw, returned_stream = future.result(owner.heartbeat_interval)
                                break
                            except TimeoutError:
                                if future.done():
                                    # Completion can race the timed wait. Re-read
                                    # its outcome to distinguish that race from
                                    # an actual provider TimeoutError.
                                    raw, returned_stream = future.result()
                                    break
                                self.wfile.write(b": keepalive\n\n")
                                self.wfile.flush()
                        if not returned_stream:
                            raise ValueError("Unexpected response framing")
                        self.wfile.write(raw)
                        self.wfile.flush()
                    else:
                        raw, returned_stream = future.result()
                        if returned_stream:
                            raise ValueError("Unexpected response framing")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(raw)))
                        self.end_headers()
                        self.wfile.write(raw)
                    owner.delivery_event("delivered", key)
                except (BrokenPipeError, ConnectionResetError):
                    # Do not cancel the provider call or lose its eventual usage.
                    # An exact reconnect can retrieve the already-paid outcome.
                    owner.delivery_event("client_disconnected", key)
                except Exception as exc:
                    owner.delivery_event("delivery_error", key, type(exc).__name__)
                    try:
                        if stream:
                            error = json.dumps(
                                {
                                    "error": {
                                        "type": type(exc).__name__,
                                        "message": "Upstream request failed; no retry",
                                    }
                                }
                            )
                            self.wfile.write(("event: error\ndata: " + error + "\n\n").encode())
                            self.wfile.flush()
                        else:
                            self.send_error(502, type(exc).__name__)
                    except (BrokenPipeError, ConnectionResetError):
                        owner.delivery_event("client_disconnected", key)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def delivery_event(self, event, key, error=None):
        with self.delivery_lock:
            row = dict(event=event, request_sha256=key)
            if error:
                row["error_type"] = error
            self.delivery_events.append(row)
            with (self.folder / "delivery.jsonl").open("a") as handle:
                handle.write(json.dumps(row) + "\n")

    def submit_once(self, original):
        if not isinstance(original, dict) or type(original.get("stream", False)) is not bool:
            raise ValueError("Expected JSON object with a boolean stream flag")
        canonical = json.dumps(
            original, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        key = hashlib.sha256(canonical.encode()).hexdigest()
        with self.delivery_lock:
            if self.closing:
                raise RuntimeError("Delivery gateway is closing")
            replay = key in self.futures
            if not replay:
                # Freeze nested input too: queued work must match its cache key
                # even if a direct caller later mutates their original object.
                self.futures[key] = self.pool.submit(self.call, json.loads(canonical))
            future = self.futures[key]
        self.delivery_event("same_request_reused" if replay else "submitted", key)
        return future, key

    def call(self, original):
        try:
            return super().call(original)
        except Exception as exc:
            # The old HTTP handler stopped admission on every upstream error,
            # including failures with known/settled usage. Keep that property
            # in the worker, even after the requesting client disconnects.
            # Client delivery failures must NOT enter this provider-error list.
            with self.lock:
                self.errors.append({"type": type(exc).__name__})
            raise

    def close(self):
        with self.close_lock:
            with self.delivery_lock:
                if self.closing:
                    return
                self.closing = True
            # Settle accepted work; atomically stop any new admissions before
            # shutting the pool down. Exact replays after close are rejected.
            self.server.shutdown()
            self.pool.shutdown(wait=True, cancel_futures=False)
            self.server.server_close()
            self.thread.join()
