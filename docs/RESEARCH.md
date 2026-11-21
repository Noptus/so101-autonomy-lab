# Implementation research — 2026-11-21

Primary references inspected before implementation:

| Source | Findings applied here |
|---|---|
| [Official LeRobot](https://github.com/huggingface/lerobot) and [SO-101 guide](https://huggingface.co/docs/lerobot/main/so101) | Use SO101Follower/Config, connect(calibrate=False), six exact `.pos` keys, saved motor calibration and explicit use_degrees=True. |
| [so101-control](https://github.com/vi-vi-3482/so101-control) | Useful degree-based wrapper and current-pose IK pattern; five positioning joints and a separate gripper. Placo's native dependency chain adds installation complexity. No GPL implementation code was copied. |
| [so-paint](https://github.com/pham-tuan-binh/so-paint) | Separate Python motion from agent intent; measured station/tool geometry, inspect actual images, seed measured position before torque configuration, distinguish mesh visualization from collision checking. |
| [SO-ARM100 model](https://github.com/TheRobotStudio/SO-ARM100) | Original SO-101 calibrated URDF; provenance/hash and Apache license preserved in assets. |
| [SO-101 chess project](https://www.kripner.com/posts/chess-robot/) | Physical chess needs board state, independent perception and grasp/alignment verification. A VLA can be useful later but is not required for deterministic registered-piece planning. |
| [SO-101 keyboard typer](https://github.com/ardacinardemirtas/so101-keyboard-typer) | Calibration and geometric mapping matter for visual manipulation; avoid presenting monocular interpretation as reliable depth/contact. |

Reviewed source commits: LeRobot `b13b952556c597d1e0849cadb6b6e7496bc5a2f3`
(main, version 0.7.1), so101-control `7461e9ed741bdc607818b3f819a8ce8e75f869f5`,
so-paint `3209abe06939007fc9a3cf60dfbd55fc82bb6200`. The actual installed and
locked LeRobot release is **0.7.0**, not the unreleased main version. Its config,
connect, send_action and observation signatures were inspected directly and tested
without opening hardware. `use_degrees` defaults true in this release and is still
set explicitly here. Older examples that silently assume different normalization
are not interchangeable.

We selected bounded SciPy IK on the original URDF after evaluating LeRobot/Placo
and so101-control. It supports the same local path on macOS/Linux and core Windows
simulation without a native Placo dependency. Capsule collision geometry and optional
MuJoCo approximations remain experimental; no full-mesh/contact safety is claimed.

## Model protocols

- [OpenAI Chat API](https://developers.openai.com/api/reference/resources/chat):
  messages, image inputs, function tools and tool-result IDs.
- [Anthropic Messages](https://platform.claude.com/docs/en/api/messages): native
  image blocks, tool_use/tool_result, model-list pagination and reported token usage.
  We use the supported `2023-06-01` version header and do not replay private reasoning.
- [Gemini compatibility documentation](https://ai.google.dev/gemini-api/docs/openai):
  preset for its OpenAI-compatible endpoint. Availability still requires a live probe.
- [OpenRouter model metadata](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties):
  advertised image modalities and supported tool parameters are hints, not validation.
- [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility) and
  [tool calling](https://docs.ollama.com/capabilities/tool-calling): local compatible
  endpoints; individual installed models differ in capabilities.
- [Mistral model list](https://docs.mistral.ai/api/endpoint/models) and
  [xAI function calling](https://docs.x.ai/developers/tools/function-calling):
  compatible presets, tested through the common image/tool probe.

There are eleven endpoint presets including native Anthropic, cloud compatible
providers, Ollama, LM Studio and a custom server. Actual model IDs come from the
selected provider, not a stale hand-written catalogue. HTTP contract tests use stub
responses. No live model/provider key was used during initial development, so no
claim of live compatibility with every provider or model is made.

## License

Project source is GPL-3.0-or-later, consistent with distributing an application using
python-chess. The original robot URDF remains Apache-2.0 under its preserved license.
External LeRobot and provider dependencies retain their respective licenses. No
third-party pretrained policy weights or private data are distributed.
