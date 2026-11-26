"""Bounded PhiBuddy event handoff; data only, never execution authority."""
import hashlib
import json

MAX_EXPORT = 8 * 1024 * 1024
MAX_PACKET = 32 * 1024
FIELDS = {"sequence", "schema_version", "session_id", "turn_id", "kind",
          "actor", "content", "created_at"}
KINDS = {"turn_started", "memory_attached", "source_passage_attached",
         "agent_draft", "agent_critique", "synthesis", "solo_answer",
         "workshop_plan", "workshop_ideas", "workshop_build", "turn_completed",
         "turn_failed", "turn_cancelled", "stage_partial"}
ANSWERS = {"synthesis", "solo_answer", "workshop_build"}


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def invalid_constant(_):
    raise ValueError("nonstandard constant")


def decode(raw):
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique,
                      parse_constant=invalid_constant)


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("ascii")


def event_valid(event):
    if type(event) is not dict or set(event) != FIELDS:
        raise ValueError("event fields")
    if type(event["schema_version"]) is not int or event["schema_version"] != 1:
        raise ValueError("event schema")
    if type(event["sequence"]) is not int or not 0 < event["sequence"] < 2**63:
        raise ValueError("event sequence")
    for field in ("session_id", "turn_id", "created_at"):
        if type(event[field]) is not str or not 0 < len(event[field]) <= 256:
            raise ValueError("event identity")
    if type(event["kind"]) is not str or event["kind"] not in KINDS:
        raise ValueError("event kind")
    if event["actor"] is not None and (type(event["actor"]) is not str
                                      or len(event["actor"]) > 128):
        raise ValueError("actor")
    if type(event["content"]) is not str:
        raise ValueError("event content")


def select(raw, sequence):
    if len(raw) > MAX_EXPORT:
        raise ValueError("export size")
    events = [decode(line) for line in raw.splitlines() if line.strip()]
    previous = 0
    sessions = set()
    for event in events:
        event_valid(event)
        if event["sequence"] <= previous:
            raise ValueError("non-increasing event order")
        previous = event["sequence"]
        sessions.add(event["session_id"])
    if len(sessions) != 1:
        raise ValueError("expected one session")
    selected = next((e for e in events if e["sequence"] == sequence), None)
    if selected is None or selected["kind"] not in ANSWERS:
        raise ValueError("select one answer event")
    turn = [e for e in events if e["turn_id"] == selected["turn_id"]]
    if (turn[0]["kind"] != "turn_started" or turn[-1]["kind"] != "turn_completed"
            or selected["sequence"] >= turn[-1]["sequence"]
            or sum(e["kind"] == "turn_started" for e in turn) != 1
            or sum(e["kind"] == "turn_completed" for e in turn) != 1
            or any(e["kind"] in {"turn_failed", "turn_cancelled"} for e in turn)):
        raise ValueError("turn not cleanly completed")
    body = {"schema": "phibuddy.advisory.v1", "event": selected,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "completion_sequence": turn[-1]["sequence"]}
    packet = dict(body, packet_sha256=hashlib.sha256(canonical(body)).hexdigest())
    validate(packet)
    return packet


def validate(packet):
    if type(packet) is not dict or set(packet) != {
        "schema", "event", "source_sha256", "completion_sequence", "packet_sha256"
    } or packet["schema"] != "phibuddy.advisory.v1":
        raise ValueError("packet schema")
    if len(canonical(packet)) > MAX_PACKET:
        raise ValueError("packet size")
    for key in ("source_sha256", "packet_sha256"):
        value = packet[key]
        if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("digest format")
    event = packet["event"]
    event_valid(event)
    if event["kind"] not in ANSWERS or not event["content"].strip():
        raise ValueError("answer required")
    end = packet["completion_sequence"]
    if type(end) is not int or not event["sequence"] < end < 2**63:
        raise ValueError("completion sequence")
    body = {key: value for key, value in packet.items() if key != "packet_sha256"}
    if hashlib.sha256(canonical(body)).hexdigest() != packet["packet_sha256"]:
        raise ValueError("packet digest")
    return {"schema": "agentora.phibuddy-advisory-receipt.v1",
            "packet_sha256": packet["packet_sha256"],
            "state": "RECEIVED_REVIEW_ONLY", "source_verified": False,
            "completion_verified": False, "execution_authority": False,
            "persisted": False, "model_called": False}
