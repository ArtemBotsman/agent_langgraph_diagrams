"""Loopback HTTP only. Scripted responses are not LLM quality evidence."""

import http.client
import json
import socket
import struct
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from jury_delivery_gateway import DeliveryGateway
from jury_opencode_gateway import as_sse
from run_fair_baseline_experiment import ExperimentBudget, ExperimentCostCeiling, ExperimentPaused


def response(finish="stop"):
    return json.dumps(
        dict(
            id="scripted",
            model="deepseek-flash",
            created=1790701200,
            choices=[
                dict(
                    index=0,
                    message=dict(role="assistant", content="unchanged"),
                    finish_reason=finish,
                )
            ],
            usage=dict(
                prompt_tokens=100,
                completion_tokens=10,
                total_tokens=110,
                prompt_cache_hit_tokens=90,
                prompt_cache_miss_tokens=10,
            ),
        )
    ).encode()


@pytest.fixture
def make_gateway(tmp_path, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: pytest.fail("No external API"))
    gateways = []

    def make(transport=lambda _: response(), ceiling=1):
        folder = tmp_path / str(len(gateways))
        folder.mkdir()
        gateway = DeliveryGateway(
            "deepseek",
            ExperimentBudget(folder, ceiling),
            folder / "gateway",
            "offline",
            transport=transport,
            max_run_tokens=None,
            output_tokens=131072,
            heartbeat_interval=0.02,
        )
        gateways.append(gateway)
        return gateway

    yield make
    for gateway in gateways:
        gateway.close()


def request(gateway, payload, auth=True):
    conn = http.client.HTTPConnection(*gateway.server.server_address, timeout=2)
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = "Bearer " + gateway.token
    conn.request("POST", "/v1/chat/completions", json.dumps(payload), headers)
    return conn, conn.getresponse()


def payload(stream=True):
    return dict(model="deepseek-flash", messages=[dict(role="user", content="test")], stream=stream)


def test_headers_and_heartbeats_arrive_before_slow_provider(make_gateway):
    release, started = threading.Event(), threading.Event()

    def transport(_):
        started.set()
        assert release.wait(2)
        return response()

    gateway = make_gateway(transport)
    conn, reply = request(gateway, payload())
    try:
        assert reply.status == 200 and started.wait(1)
        assert reply.readline().startswith(b": budgeted")
        assert reply.readline() == b"\n"
        assert reply.readline() == b": keepalive\n"
        release.set()
        remainder = reply.read()
        assert remainder.endswith(as_sse(json.loads(response())))
    finally:
        release.set()
        conn.close()
    assert len(gateway.calls) == 1 and not gateway.budget.reservations


def test_inflight_and_completed_duplicates_share_one_paid_call(make_gateway):
    release = threading.Event()

    def transport(_):
        assert release.wait(2)
        return response("length")

    gateway = make_gateway(transport)
    first, key = gateway.submit_once(payload())
    second, second_key = gateway.submit_once(payload())
    assert first is second and key == second_key
    release.set()
    raw, _ = first.result(2)
    third, _ = gateway.submit_once(payload())
    assert third is first and b'"length"' in raw
    assert len(gateway.calls) == 1
    assert sum(e["event"] == "same_request_reused" for e in gateway.delivery_events) == 2


def test_different_request_not_merged(make_gateway):
    gateway = make_gateway()
    one, _ = gateway.submit_once(payload())
    two, _ = gateway.submit_once(
        {**payload(), "messages": [dict(role="user", content="different")]}
    )
    one.result(2)
    two.result(2)
    assert len(gateway.calls) == 2


def test_nonstream_exact_bytes_and_unauthorized_no_charge(make_gateway):
    gateway = make_gateway()
    conn, reply = request(gateway, payload(False), auth=False)
    assert reply.status == 403
    conn.close()
    assert not gateway.calls
    conn, reply = request(gateway, payload(False))
    assert reply.status == 200 and reply.read() == response()
    conn.close()
    assert len(gateway.calls) == 1


def test_provider_failure_retains_reservation_and_is_not_retried(make_gateway):
    invocations = []

    def transport(_):
        invocations.append(1)
        raise TimeoutError("scripted")

    gateway = make_gateway(transport)
    first, _ = gateway.submit_once(payload())
    with pytest.raises(TimeoutError):
        first.result(2)
    again, _ = gateway.submit_once(payload())
    with pytest.raises(TimeoutError):
        again.result(2)
    assert len(invocations) == 1 and gateway.budget.pause_reason
    assert gateway.budget.spent > 0 and not gateway.calls


def test_budget_denial_before_transmission(make_gateway):
    invoked = []
    gateway = make_gateway(lambda _: invoked.append(1), ceiling=0.000001)
    future, _ = gateway.submit_once(payload())
    with pytest.raises(ExperimentCostCeiling):
        future.result(2)
    assert invoked == [] and not gateway.calls


def test_concurrent_same_request_is_one_settled_call(make_gateway):
    gateway = make_gateway()
    barrier = threading.Barrier(8)

    def submit(_):
        barrier.wait(timeout=2)
        return gateway.submit_once(payload())[0]

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = list(pool.map(submit, range(8)))
    assert all(future is futures[0] for future in futures)
    futures[0].result(2)
    ledger = [json.loads(line) for line in gateway.budget.path.read_text().splitlines()]
    assert [row["event"] for row in ledger] == ["reserve", "settle"]
    assert len(gateway.calls) == 1 and not gateway.budget.reservations


def test_queued_request_is_immutable_snapshot(make_gateway):
    release, started = threading.Event(), threading.Event()
    seen = []

    def transport(data):
        seen.append(data["messages"][0]["content"])
        started.set()
        assert release.wait(2)
        return response()

    gateway = make_gateway(transport)
    first, _ = gateway.submit_once(payload())
    assert started.wait(1)
    original = {**payload(), "messages": [dict(role="user", content="queued")]}
    second, _ = gateway.submit_once(original)
    original["messages"][0]["content"] = "mutated"
    release.set()
    first.result(2)
    second.result(2)
    assert seen == ["test", "queued"]


def test_known_usage_failure_stops_later_distinct_request(make_gateway):
    invoked = []

    def transport(_):
        invoked.append(1)
        data = json.loads(response())
        data["model"] = "unexpected"
        return json.dumps(data).encode()

    gateway = make_gateway(transport)
    failed, _ = gateway.submit_once(payload())
    with pytest.raises(ValueError, match="Returned model mismatch"):
        failed.result(2)
    later, _ = gateway.submit_once({**payload(), "messages": []})
    with pytest.raises(ExperimentPaused):
        later.result(2)
    replay, _ = gateway.submit_once(payload())
    assert replay is failed
    assert invoked == [1] and gateway.errors
    assert gateway.budget.spent > 0 and not gateway.budget.reservations


def test_timeout_completion_race_delivers_success(make_gateway, monkeypatch):
    gateway = make_gateway()
    future, _ = gateway.submit_once(payload())
    raw, _ = future.result(2)
    actual_result = future.result
    raced = False

    def racing_result(timeout=None):
        nonlocal raced
        if timeout is not None and not raced:
            raced = True
            raise TimeoutError("timed wait raced with successful completion")
        return actual_result(timeout)

    monkeypatch.setattr(future, "result", racing_result)
    conn, reply = request(gateway, payload())
    try:
        received = reply.read()
    finally:
        conn.close()
    assert raced and received.endswith(raw)
    assert b"event: error" not in received and len(gateway.calls) == 1


def test_http_provider_timeout_is_error_and_replay_not_retried(make_gateway):
    invoked = []

    def transport(_):
        invoked.append(1)
        raise TimeoutError("scripted provider timeout")

    gateway = make_gateway(transport)
    for _ in range(2):
        conn, reply = request(gateway, payload())
        try:
            received = reply.read()
        finally:
            conn.close()
        assert b"event: error" in received and b'"type": "TimeoutError"' in received
        assert b"[DONE]" not in received
    assert invoked == [1] and gateway.budget.pause_reason


def test_disconnect_does_not_cancel_or_duplicate_accounting(make_gateway):
    release, started = threading.Event(), threading.Event()

    def transport(_):
        started.set()
        assert release.wait(2)
        return response()

    gateway = make_gateway(transport)
    conn, reply = request(gateway, payload())
    try:
        assert reply.readline().startswith(b": budgeted") and started.wait(1)
        # Force a TCP reset while the provider is pending, rather than relying
        # on how the client's response file owns the socket after getresponse.
        sock = reply.fp.raw._sock
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        reply.close()
        conn.close()
        deadline = time.monotonic() + 1
        while not any(e["event"] == "client_disconnected" for e in gateway.delivery_events):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert gateway.budget.reservations
        future, _ = gateway.submit_once(payload())
        assert not future.cancelled()
        release.set()
        expected, _ = future.result(2)
        reconnect, replay = request(gateway, payload())
        try:
            assert replay.read().endswith(expected)
        finally:
            reconnect.close()
        assert len(gateway.calls) == 1 and not gateway.budget.reservations
        assert gateway.errors == []
    finally:
        release.set()
        reply.close()
        conn.close()


def test_close_settles_pending_work_and_rejects_new_admission(make_gateway):
    release, started = threading.Event(), threading.Event()

    def transport(_):
        started.set()
        assert release.wait(2)
        return response()

    gateway = make_gateway(transport)
    future, _ = gateway.submit_once(payload())
    assert started.wait(1)
    closer = threading.Thread(target=gateway.close)
    closer.start()
    try:
        deadline = time.monotonic() + 1
        while not gateway.closing:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        with pytest.raises(RuntimeError, match="closing"):
            gateway.submit_once({**payload(), "messages": []})
        assert closer.is_alive()
    finally:
        release.set()
        closer.join(3)
    assert not closer.is_alive()
    future.result(1)
    assert len(gateway.calls) == 1 and not gateway.budget.reservations
    gateway.close()  # Idempotent, including the fixture's final close.


@pytest.mark.parametrize("bad", [[], {**payload(), "stream": "false"}, {"value": float("nan")}])
def test_invalid_json_shape_is_rejected_without_charge(make_gateway, bad):
    gateway = make_gateway()
    conn, reply = request(gateway, bad)
    try:
        assert reply.status == 400
    finally:
        conn.close()
    assert not gateway.calls and not gateway.futures


def test_incomplete_http_body_is_not_submitted(make_gateway):
    gateway = make_gateway()
    body = json.dumps(payload()).encode()
    conn = http.client.HTTPConnection(*gateway.server.server_address, timeout=2)
    try:
        conn.request(
            "POST",
            "/v1/chat/completions",
            body,
            {"Authorization": "Bearer " + gateway.token, "Content-Length": str(len(body) + 8)},
        )
        conn.sock.shutdown(socket.SHUT_WR)
        assert conn.getresponse().status == 400
    finally:
        conn.close()
    assert not gateway.calls and not gateway.futures


@pytest.mark.parametrize("interval", [0, -1, float("nan"), float("inf")])
def test_invalid_heartbeat_is_rejected_before_start(interval):
    with pytest.raises(ValueError, match="Heartbeat interval"):
        DeliveryGateway(heartbeat_interval=interval)
