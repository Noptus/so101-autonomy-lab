import asyncio
import json
import time
import httpx
import pytest
from so101_lab.agents.providers import Provider, ProviderConfig, ProviderError, anthropic_messages, PRESETS


@pytest.mark.parametrize("preset", list(PRESETS))
def test_provider_endpoint_presets(preset):
    protocol, url, env = ProviderConfig(preset=preset).resolved()
    assert protocol in ("openai", "anthropic") and url.startswith(("https://", "http://127.0.0.1"))


@pytest.mark.parametrize(
    "url", ["http://example.com/v1", "https://user:key@example.com/v1", "https://example.com/v1?api_key=x"]
)
def test_insecure_or_credential_endpoint_rejected(url):
    with pytest.raises(ValueError):
        ProviderConfig(base_url=url).resolved()


async def test_openai_compatible_tool_and_image_roundtrip():
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "actual-vision-model"}]})
        payload = json.loads(request.content)
        assert payload["model"] == "actual-vision-model" and payload["tools"]
        assert any(i["type"] == "image_url" for i in payload["messages"][0]["content"])
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "reasoning_content": "PRIVATE",
                            "tool_calls": [
                                {
                                    "id": "t1",
                                    "type": "function",
                                    "function": {"name": "capability_check", "arguments": '{"color":"red"}'},
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    provider = Provider(ProviderConfig(model="actual-vision-model"), "test-key", httpx.MockTransport(handler))
    assert (await provider.models())[0]["id"] == "actual-vision-model"
    result = await provider.probe()
    assert result["ok"] and result["usage"]["input_tokens"] == 5


async def test_anthropic_transcript_and_native_tool_response():
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        assert request.headers["x-api-key"] == "test"
        return httpx.Response(
            200,
            json={
                "content": [{"type": "tool_use", "id": "u1", "name": "get_robot_state", "input": {}}],
                "usage": {"input_tokens": 4, "output_tokens": 2},
            },
        )

    p = Provider(
        ProviderConfig(preset="anthropic", model="discovered-model"), "test", httpx.MockTransport(handler)
    )
    messages = [{"role": "system", "content": "instructions"}, {"role": "user", "content": "look"}]
    answer, usage = await p.complete(messages, [])
    messages += [answer, {"role": "tool", "tool_call_id": "u1", "content": '{"ok":true}'}]
    translated = anthropic_messages(messages)
    assert translated[-1]["content"][0]["tool_use_id"] == "u1"
    assert translated[-2]["content"][0]["type"] == "tool_use"
    assert usage["output_tokens"] == 2 and calls[0]["max_tokens"] == 2048


async def test_provider_timeout_and_secret_error_sanitization():
    def timeout(request):
        raise httpx.ReadTimeout("key=SECRET")

    p = Provider(ProviderConfig(model="test"), "SECRET", httpx.MockTransport(timeout))
    with pytest.raises(ProviderError, match="timeout") as error:
        await p.complete([], [])
    assert "SECRET" not in str(error.value)
    p = Provider(
        ProviderConfig(model="test"),
        "SECRET",
        httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "SECRET"})),
    )
    with pytest.raises(ProviderError) as error:
        await p.models()
    assert "SECRET" not in str(error.value)


def test_keys_are_scoped_to_endpoint(lab):
    a = ProviderConfig(preset="openai")
    b = ProviderConfig(preset="custom", base_url="http://127.0.0.1:9999/v1")
    lab.secrets.put(a, "fake-scoped-key")
    assert lab.secrets.get(a) == "fake-scoped-key"
    assert lab.secrets.get(b) != "fake-scoped-key"


async def test_stop_cancels_waiting_model_without_waiting_timeout(lab, monkeypatch):
    import so101_lab.agents.supervisor as module

    started = asyncio.Event()

    class SlowProvider:
        def __init__(self, *args):
            pass

        async def complete(self, *args):
            started.set()
            await asyncio.sleep(10)

    monkeypatch.setattr(module, "Provider", SlowProvider)
    lab.provider_config = ProviderConfig(model="fake")
    lab.memory.save("provider_probe", {"identity": lab.provider_identity(), "time": time.time()})
    task = asyncio.create_task(lab.supervisor.run("observe"))
    await asyncio.wait_for(started.wait(), 1)
    begin = time.monotonic()
    lab.supervisor.stop()
    result = await asyncio.wait_for(task, 1)
    assert time.monotonic() - begin < 0.5 and result["status"] == "stopped"
    assert not lab.robot.commands


async def test_agent_rejects_unknown_tools_and_persists_result(lab, monkeypatch):
    import so101_lab.agents.supervisor as module

    class BadProvider:
        def __init__(self, *args):
            pass

        async def complete(self, *args):
            return {
                "role": "assistant",
                "content": "Inspecting",
                "tool_calls": [{"id": "evil", "function": {"name": "disable_safety", "arguments": "{}"}}],
            }, {"input_tokens": 3, "output_tokens": 1}

    monkeypatch.setattr(module, "Provider", BadProvider)
    lab.provider_config = ProviderConfig(model="fake")
    lab.memory.save("provider_probe", {"identity": lab.provider_identity(), "time": time.time()})
    result = await lab.supervisor.run("move")
    assert result["status"] == "needs_operator_or_replan"
    assert result["input_tokens"] == 3 and result["estimated_cost_usd"] is None
    assert not lab.robot.commands
    assert lab.memory.get("last_agent_session")["status"] == result["status"]


async def test_agent_deadline_stops_without_automatic_retry(lab, monkeypatch):
    import so101_lab.agents.supervisor as module

    class HungProvider:
        def __init__(self, *args):
            pass

        async def complete(self, *args):
            await asyncio.sleep(10)

    monkeypatch.setattr(module, "Provider", HungProvider)
    lab.provider_config = ProviderConfig(model="fake", timeout=0.05)
    lab.memory.save("provider_probe", {"identity": lab.provider_identity(), "time": time.time()})
    result = await asyncio.wait_for(lab.supervisor.run("observe"), 2)
    assert result["status"] == "failed" and lab.controller.stopped.is_set()
    assert "timeout" in result["error"].lower()
    assert not lab.robot.commands
