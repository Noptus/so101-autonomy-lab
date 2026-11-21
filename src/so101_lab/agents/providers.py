"""Thin HTTP transports with a normalized tool transcript; no arbitrary model execution."""

from __future__ import annotations

import base64
import json
import os
from urllib.parse import urlparse

import httpx
from pydantic import Field
from so101_lab.domain import Validated

PRESETS = {
    "openai": ("openai", "https://api.openai.com/v1", "OPENAI_API_KEY"),
    "anthropic": ("anthropic", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY"),
    "gemini": ("openai", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    "openrouter": ("openai", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "mistral": ("openai", "https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    "xai": ("openai", "https://api.x.ai/v1", "XAI_API_KEY"),
    "groq": ("openai", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "together": ("openai", "https://api.together.xyz/v1", "TOGETHER_API_KEY"),
    "ollama": ("openai", "http://127.0.0.1:11434/v1", ""),
    "lmstudio": ("openai", "http://127.0.0.1:1234/v1", ""),
    "custom": ("openai", "http://127.0.0.1:8000/v1", "SO101_MODEL_API_KEY"),
}


class ProviderConfig(Validated):
    preset: str = "openai"
    model: str = ""
    base_url: str = ""
    protocol: str = ""
    share_images: bool = False
    max_output_tokens: int = Field(default=2048, ge=128, le=16384)
    timeout: float = Field(default=40, ge=0.05, le=120)
    input_price_per_million: float | None = Field(default=None, ge=0)
    output_price_per_million: float | None = Field(default=None, ge=0)

    def resolved(self):
        if self.preset not in PRESETS:
            raise ValueError("Unknown provider preset")
        protocol, url, env = PRESETS[self.preset]
        url = (self.base_url or url).rstrip("/")
        parsed = urlparse(url)
        if not parsed.hostname:
            raise ValueError("Endpoint needs a hostname")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Endpoint must not contain credentials, queries or fragments")
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")
        ):
            raise ValueError("Use HTTPS, or HTTP on a loopback address")
        protocol = self.protocol or protocol
        if protocol not in ("openai", "anthropic"):
            raise ValueError("Protocol must be openai or anthropic")
        return protocol, url, env


class SecretStore:
    def __init__(self, memory):
        self.keys = {}
        self.memory = memory

    @staticmethod
    def identity(config):
        # Keys are scoped to endpoints: changing endpoint cannot exfiltrate another provider's key.
        return config.resolved()[1]

    def put(self, config, key, persist=False):
        identity = self.identity(config)
        self.keys[identity] = key
        self.memory.secrets.add(key)
        if persist:
            import keyring

            try:
                backend = keyring.get_keyring()
                if "plaintext" in type(backend).__name__.lower() or backend.priority <= 0:
                    raise RuntimeError("No secure OS keychain")
                keyring.set_password("so101-autonomy-lab", identity, key)
                self.memory.save("keychain:" + identity, True)
            except Exception as exc:
                raise ValueError("OS keychain unavailable; key remains in memory for this session") from exc

    def get(self, config):
        protocol, url, env = config.resolved()
        key = self.keys.get(url)
        if not key:
            # Environment keys only apply to the preset's original endpoint.
            if url == PRESETS[config.preset][1].rstrip("/"):
                key = os.getenv(env, "") if env else ""
            if not key and self.memory.get("keychain:" + url, False):
                try:
                    import keyring

                    key = keyring.get_password("so101-autonomy-lab", url)
                except Exception:
                    key = ""
        if key:
            self.memory.secrets.add(key)
        return key or ""


class ProviderError(RuntimeError):
    pass


def anthropic_messages(messages):
    """Translate OpenAI-style tool turns while preserving tool IDs and multimodal images."""
    result = []
    for m in messages:
        if m["role"] == "system":
            continue
        if m["role"] == "tool":
            role, blocks = (
                "user",
                [{"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}],
            )
        else:
            role = m["role"]
            content = m.get("content") or ""
            blocks = []
            if isinstance(content, str):
                if content:
                    blocks.append({"type": "text", "text": content})
            else:
                for item in content:
                    if item["type"] == "text":
                        blocks.append(item)
                    elif item["type"] == "image_url":
                        header, data = item["image_url"]["url"].split(",", 1)
                        blocks.append(
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": header.split(":")[1].split(";")[0],
                                    "data": data,
                                },
                            }
                        )
            for call in m.get("tool_calls", []):
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": call["function"]["name"],
                        "input": json.loads(call["function"]["arguments"]),
                    }
                )
        if not blocks:
            blocks = [{"type": "text", "text": "Continue."}]
        if result and result[-1]["role"] == role:
            result[-1]["content"].extend(blocks)
        else:
            result.append({"role": role, "content": blocks})
    return result


class Provider:
    def __init__(self, config, key="", transport=None):
        self.config = config
        self.protocol, self.url, _ = config.resolved()
        self.key = key
        self.transport = transport

    def headers(self):
        if self.protocol == "anthropic":
            return {"x-api-key": self.key, "anthropic-version": "2023-06-01"}
        return {"Authorization": f"Bearer {self.key}"} if self.key else {}

    async def request(self, method, path, **kwargs):
        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.request(method, self.url + path, headers=self.headers(), **kwargs)
                if response.status_code >= 300:
                    # Do not echo provider payloads or URLs containing credentials.
                    raise ProviderError(
                        f"Provider returned HTTP {response.status_code}; check key, endpoint and model capabilities"
                    )
                return response.json()
        except httpx.TimeoutException as exc:
            raise ProviderError("Provider timeout; robot motion did not resume") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError("Provider response or connection failed") from exc

    async def models(self):
        models, cursor = [], None
        for _ in range(10):
            path = "/models" + (f"?after_id={cursor}" if cursor else "")
            data = await self.request("GET", path)
            for m in data.get("data", []):
                modalities = m.get("architecture", {}).get("input_modalities", [])
                params = m.get("supported_parameters", [])
                models.append(
                    {
                        "id": m["id"],
                        "name": m.get("name", m.get("display_name", m["id"])),
                        "vision": "image" in modalities if modalities else None,
                        "tools": "tools" in params if params else None,
                        "capability_status": "advertised; probe before use",
                    }
                )
            if not data.get("has_more"):
                break
            cursor = data.get("last_id")
            if not cursor:
                break
        return models

    async def complete(self, messages, tools):
        if not self.config.model:
            raise ProviderError("Select an actual available model")
        if self.protocol == "anthropic":
            payload = {
                "model": self.config.model,
                "max_tokens": self.config.max_output_tokens,
                "system": "\n".join(m["content"] for m in messages if m["role"] == "system"),
                "messages": anthropic_messages(messages),
            }
            if tools:
                payload["tools"] = [
                    {
                        "name": t["function"]["name"],
                        "description": t["function"]["description"],
                        "input_schema": t["function"]["parameters"],
                    }
                    for t in tools
                ]
            raw = await self.request("POST", "/messages", json=payload)
            text = "\n".join(b["text"] for b in raw.get("content", []) if b["type"] == "text")
            calls = [
                {
                    "id": b["id"],
                    "type": "function",
                    "function": {"name": b["name"], "arguments": json.dumps(b["input"])},
                }
                for b in raw.get("content", [])
                if b["type"] == "tool_use"
            ]
            usage = raw.get("usage", {})
            return {"role": "assistant", "content": text, "tool_calls": calls}, {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            }
        raw = await self.request(
            "POST",
            "/chat/completions",
            json={
                "model": self.config.model,
                "messages": messages,
                (
                    "max_completion_tokens" if self.config.preset == "openai" else "max_tokens"
                ): self.config.max_output_tokens,
                **({"tools": tools, "tool_choice": "auto"} if tools else {}),
            },
        )
        m = raw["choices"][0]["message"]
        # Private reasoning fields from compatible servers are deliberately discarded.
        answer = {"role": "assistant", "content": m.get("content") or ""}
        if m.get("tool_calls"):
            answer["tool_calls"] = m["tool_calls"]
        usage = raw.get("usage", {})
        return answer, {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        }

    async def probe(self):
        # Synthetic image: no workspace image leaves the machine during capability testing.
        import cv2
        import numpy as np

        ok, buf = cv2.imencode(".png", np.full((32, 32, 3), (0, 0, 255), np.uint8))
        uri = "data:image/png;base64," + base64.b64encode(buf).decode()
        tool = {
            "type": "function",
            "function": {
                "name": "capability_check",
                "description": "Report the observed square color",
                "parameters": {
                    "type": "object",
                    "properties": {"color": {"type": "string", "enum": ["red", "blue", "green"]}},
                    "required": ["color"],
                    "additionalProperties": False,
                },
            },
        }
        answer, usage = await self.complete(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Look at this image. Call capability_check with its color. Do not respond in text.",
                        },
                        {"type": "image_url", "image_url": {"url": uri}},
                    ],
                }
            ],
            [tool],
        )
        for call in answer.get("tool_calls", []):
            try:
                if call["function"]["name"] == "capability_check" and json.loads(
                    call["function"]["arguments"]
                ) == {"color": "red"}:
                    return {
                        "ok": True,
                        "model": self.config.model,
                        "vision_and_tools": "synthetic probe passed",
                        "usage": usage,
                    }
            except (ValueError, KeyError):
                pass
        raise ProviderError("Model did not pass image + structured tool probe; choose another model")
