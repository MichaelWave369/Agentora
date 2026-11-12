"""Unit tests for the opt-in PhiDiscovery bridge; no GPU or network required."""
import asyncio
import hashlib
import json
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from app.routers.discovery import authorize, evaluate, validate_packet


class FakeRequest:
    class Client:
        host = "127.0.0.1"
    class Url:
        hostname = "127.0.0.1"
    client = Client()
    url = Url()
    headers = {}


def packet():
    out = {
        "candidate_id": "C-1",
        "role": "assumption_challenger",
        "system": "Untrusted role prompt",
        "instruction": "Untrusted task text",
        "context": {"candidate_id": "C-1", "hypothesis": "test",
                    "evidence": [{"id": "E-1", "statement_unverified": "toy"}]},
    }
    out["packet_id"] = hashlib.sha256(json.dumps(
        out, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode("utf-8")).hexdigest()
    return out


class FakeOllama:
    async def chat_structured(self, model, system, prompt, schema):
        assert "Untrusted role prompt" not in system
        assert "Untrusted task text" not in system
        assert "peer_answers" not in prompt
        return {
            "stance": "unresolved",
            "analysis": "Evidence has not been validated.",
            "counterexample": "A different explanation may exist.",
            "discriminating_prediction": "Alternative predicts a different observation.",
            "test_design": "Use controlled, preregistered comparisons.",
            "cited_evidence_ids": ["E-1"],
            "uncertainties": ["Synthetic exercise"],
        }


class DiscoveryBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_review_without_tools_or_memory(self):
        result = await evaluate(packet(), "test-model", client=FakeOllama())
        self.assertEqual(result["schema"], "agentora.discovery-review.v0.3")
        self.assertEqual(result["packet_id"], packet()["packet_id"])
        self.assertEqual(result["tool_calls"], 0)
        self.assertFalse(result["memory_used"])
        self.assertFalse(result["evidence_verified"])
        self.assertTrue(result["human_review_required"])

    async def test_tampering_is_detected(self):
        p = packet()
        p["context"]["hypothesis"] = "tampered"
        with self.assertRaises(ValueError):
            await evaluate(p, "test-model", client=FakeOllama())

    async def test_forged_role_is_detected(self):
        p = packet()
        p["role"] = "system"
        with self.assertRaises(ValueError):
            await evaluate(p, "test-model", client=FakeOllama())

    async def test_missing_fields_rejected(self):
        p = packet()
        p.pop("instruction")
        with self.assertRaises(ValueError):
            await evaluate(p, "test-model", client=FakeOllama())

    async def test_disabled_by_default(self):
        with patch.dict(os.environ, {"AGENTORA_DISCOVERY_REVIEW_ENABLED": "false",
                                     "AGENTORA_DISCOVERY_REVIEW_KEY": "x" * 30}, clear=False):
            with self.assertRaises(HTTPException) as cm:
                authorize(FakeRequest(), "x" * 30, "test-model")
            self.assertEqual(cm.exception.status_code, 404)

    async def test_rejects_bad_key_and_nonloopback(self):
        with patch.dict(os.environ, {
            "AGENTORA_DISCOVERY_REVIEW_ENABLED": "true",
            "AGENTORA_DISCOVERY_REVIEW_KEY": "x" * 30,
            "AGENTORA_DISCOVERY_REVIEW_MODELS": "test-model",
        }, clear=False):
            with self.assertRaises(HTTPException):
                authorize(FakeRequest(), "wrong", "test-model")
            request = FakeRequest()
            request.client = type("Client", (), {"host": "8.8.8.8"})()
            with self.assertRaises(HTTPException):
                authorize(request, "x" * 30, "test-model")

    async def test_rejects_browser_origin(self):
        request = FakeRequest()
        request.headers = {"origin": "https://site.example"}
        with patch.dict(os.environ, {"AGENTORA_DISCOVERY_REVIEW_ENABLED": "true"}, clear=False):
            with self.assertRaises(HTTPException):
                authorize(request, "anything", "test-model")


if __name__ == "__main__":
    unittest.main()
