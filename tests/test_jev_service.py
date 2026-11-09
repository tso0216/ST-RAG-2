"""JEV 服務：真的 SDK client 接本機的假 transport，看送出的請求和怎麼讀回應。不打外部 API。"""
import asyncio
import json

import httpx2
import pytest
from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy

from service.jev import JEVClient, JEVError


def client(handler) -> JEVClient:
    return JEVClient(AsyncTypeSafeClient(api_key="test-key", transport=httpx2.MockTransport(handler),
                                         retry=RetryPolicy(max_retries=0)))


def test_sends_one_noul_question_with_the_pinned_model_and_reads_the_answered_model():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json={"model": "jev-1.14.0", "usage": {"input_tokens": 3, "output_tokens": 1},
                                          "answers": {"relevant": {"type": "noul", "noul": 0.73}}})

    state = {"question": "排隊要多久", "passage": "排了一小時"}
    a = asyncio.run(client(handler).noul("jev-1.14.0", state, "相關嗎？", {"true": "相關", "false": "無關"}))

    assert (a.noul, a.model) == (0.73, "jev-1.14.0")
    [body] = sent
    assert body["model"] == "jev-1.14.0" and body["state"] == state
    assert body["questions"] == {"relevant": {"type": "noul", "instructions": "相關嗎？",
                                              "criteria": {"true": "相關", "false": "無關"}}}


def test_http_error_becomes_jev_error():
    def handler(request):
        return httpx2.Response(500, json={"error": "壞了"})

    with pytest.raises(JEVError):
        asyncio.run(client(handler).noul("jev-1.14.0", {"passage": "x"}, "相關嗎？", {"true": "相關", "false": "無關"}))


def test_response_without_the_answer_is_a_jev_error():
    def handler(request):
        return httpx2.Response(200, json={"model": "jev-1.14.0", "usage": {"input_tokens": 3, "output_tokens": 1},
                                          "answers": {"other": {"type": "noul", "noul": 0.5}}})

    with pytest.raises(JEVError):
        asyncio.run(client(handler).noul("jev-1.14.0", {"passage": "x"}, "相關嗎？", {"true": "相關", "false": "無關"}))


def test_missing_api_key_is_a_jev_error(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(JEVError):
        JEVClient()
