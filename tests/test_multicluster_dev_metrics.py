"""dev/multicluster/cluster_metrics.py backfills Mimir with hand-encoded remote-write requests; these
guard the encoding and the clock-only values the backfill and the live target must agree on."""

from __future__ import annotations

import importlib.util
import struct
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "dev" / "multicluster" / "cluster_metrics.py"


def _load(monkeypatch, **env: str):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location("cluster_metrics", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _unsnappy_literals(data: bytes) -> bytes:
    length, offset = _read_uvarint(data, 0)
    out = bytearray()
    while offset < len(data):
        tag = data[offset]
        offset += 1
        assert tag & 0x3 == 0, "only literal elements are expected"
        n = tag >> 2
        if n == 60:
            n, offset = data[offset], offset + 1
        elif n == 61:
            n, offset = struct.unpack_from("<H", data, offset)[0], offset + 2
        out += data[offset : offset + n + 1]
        offset += n + 1
    assert len(out) == length
    return bytes(out)


def _read_uvarint(data: bytes, offset: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, offset
        shift += 7


def _fields(data: bytes):
    offset = 0
    while offset < len(data):
        key, offset = _read_uvarint(data, offset)
        number, wire = key >> 3, key & 0x7
        if wire == 2:
            size, offset = _read_uvarint(data, offset)
            yield number, data[offset : offset + size]
            offset += size
        elif wire == 1:
            yield number, struct.unpack_from("<d", data, offset)[0]
            offset += 8
        elif wire == 0:
            value, offset = _read_uvarint(data, offset)
            yield number, value


def test_write_request_round_trips_through_snappy_and_protobuf(monkeypatch) -> None:
    metrics = _load(monkeypatch)
    payload = metrics.encode_write_request([({"__name__": "up", "cluster": "eu"}, [(1_700_000_000_000, 1.5), (1_700_000_060_000, 2.0)])] * 400)

    decoded = _unsnappy_literals(metrics.snappy_literal(payload))

    assert decoded == payload
    series = [body for number, body in _fields(decoded) if number == 1]
    assert len(series) == 400
    labels, samples = [], []
    for number, body in _fields(series[0]):
        parts = dict(_fields(body))
        (labels if number == 1 else samples).append(parts)
    assert [(label[1].decode(), label[2].decode()) for label in labels] == [("__name__", "up"), ("cluster", "eu")]
    assert [(sample[2], sample[1]) for sample in samples] == [(1_700_000_000_000, 1.5), (1_700_000_060_000, 2.0)]


def test_values_depend_only_on_the_clock_and_cluster(monkeypatch) -> None:
    first = _load(monkeypatch, CLUSTER="eu").values_at(1_700_000_000)
    again = _load(monkeypatch, CLUSTER="eu").values_at(1_700_000_000)
    other = _load(monkeypatch, CLUSTER="us").values_at(1_700_000_000)

    assert first == again
    assert first["http_requests_total"]["checkout"] > other["http_requests_total"]["checkout"]


def test_incident_slows_only_the_configured_service_inside_its_window(monkeypatch) -> None:
    metrics = _load(monkeypatch, CLUSTER="us", INCIDENT_SERVICE="checkout", INCIDENT_EVERY_MINUTES="480", INCIDENT_FOR_MINUTES="15")
    during, after = 8 * 3600 * 1000 + 300, 8 * 3600 * 1000 + 3600

    assert metrics.in_incident("checkout", during) and not metrics.in_incident("checkout", after)
    assert not metrics.in_incident("payments", during)
    assert metrics.values_at(during)["request_latency_p95"]["checkout"] > 2 * metrics.values_at(after)["request_latency_p95"]["checkout"]
