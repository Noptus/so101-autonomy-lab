"use strict";
const $ = (id) => document.getElementById(id);
let auth = "",
  state = null,
  presets = {},
  modalAction = null,
  previewBusy = false,
  lastImages = new Map(),
  seenEvents = new Set();
const pretty = (x) => JSON.stringify(x, null, 2);
function toast(text, error = false) {
  const e = $("toast");
  e.textContent = text;
  e.style.display = "block";
  e.style.background = error ? "#4d2830" : "#283b33";
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (e.style.display = "none"), 7000);
}
async function api(path, body, method) {
  let response = await fetch("/api/" + path, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers: {
      "Content-Type": "application/json",
      "X-Lab-Request": "1",
      ...(auth ? { Authorization: "Bearer " + auth } : {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (response.status === 401 && !auth) {
    auth = prompt("Remote access token (kept in memory only)") || "";
    if (auth) return api(path, body, method);
  }
  if (!response.ok) {
    let data = await response
      .json()
      .catch(() => ({ detail: "Request failed" }));
    throw Error(
      typeof data.detail === "string" ? data.detail : pretty(data.detail),
    );
  }
  return response.json();
}
function act(id, handler) {
  $(id).onclick = async () => {
    try {
      await handler();
    } catch (e) {
      toast(e.message, true);
    }
  };
}
async function job(response) {
  if (!response.id) return response;
  toast("Operation started");
  while (true) {
    const status = await api("jobs/" + response.id);
    if (status.status === "failed") throw Error(status.error);
    if (status.status === "complete") {
      let result = status.result;
      const failed = result?.ok === false || result?.result?.ok === false;
      toast(
        failed
          ? result.message || result.result?.message || "Operation rejected"
          : "Operation completed; inspect recorded feedback",
        failed,
      );
      await refresh();
      if (result?.result && result?.id) {
        outcomeDialog(result);
      }
      return result;
    }
    await new Promise((r) => setTimeout(r, 400));
  }
}
function modal(
  title,
  description,
  info,
  editor,
  action,
  label = "Save",
  approval = false,
) {
  $("modal-title").textContent = title;
  $("modal-description").textContent = description;
  $("modal-info").textContent = info ? pretty(info) : "";
  $("editor-label").hidden = editor === null;
  $("editor").value = editor === null ? "" : pretty(editor);
  $("approval-label").hidden = !approval;
  $("approval").checked = false;
  $("modal-action").textContent = label;
  $("modal-action").hidden = !action;
  modalAction = action;
  $("modal").showModal();
}
act("modal-action", async () => {
  if (!$("approval-label").hidden && !$("approval").checked)
    throw Error("Review the exact plan and check the contact approval box");
  let value = $("editor-label").hidden ? null : JSON.parse($("editor").value);
  const action = modalAction;
  await action(value);
  if (modalAction === action) $("modal").close();
});
act("modal-close", () => {
  $("modal").close();
});
async function refresh() {
  state = await api("status");
  render(state);
}
function render(s) {
  $("mode").textContent =
    s.backend === "hardware" ? "PHYSICAL SO-101" : s.backend.toUpperCase();
  $("connection").textContent = s.state.connected
    ? "● Connected"
    : "○ Disconnected";
  $("device-note").textContent = s.stopped
    ? "Stop latched. Validate and resume before requesting motion."
    : s.commissioned
      ? "Motion profile active. Every trajectory is checked."
      : "Supervised commissioning is required before motion.";
  $("sharing").textContent = s.cloud_image_sharing
    ? "Images shared with " + s.provider.preset
    : "Images stay local";
  $("provider-status").textContent = s.provider_verified
    ? "Image + tool probe passed for selected model"
    : "Run the model capability probe before starting an agent";
  if (s.pose)
    $("tcp").textContent =
      "TCP estimate  " +
      s.pose
        .slice(0, 3)
        .map((r) => r[3].toFixed(4) + " m")
        .join(" / ") +
      " · " +
      (s.motion_busy ? "EXECUTING" : "IDLE");
  $("resume").disabled = s.motion_busy;
  $("explore").disabled =
    s.motion_busy || s.operation_active || s.agent_running;
  if (s.state.joints) {
    for (const [key, value] of Object.entries(s.state.joints)) {
      const id = "j-" + key.replace(".pos", "");
      let row = $(id);
      if (!row) {
        row = document.createElement("div");
        row.className = "joint";
        row.id = id;
        const label = document.createElement("span");
        label.textContent = key.replace(".pos", "").replaceAll("_", " ");
        const number = document.createElement("strong");
        row.append(label, number);
        if (key !== "gripper.pos") {
          for (const delta of [-1, 1]) {
            const button = document.createElement("button");
            button.textContent = delta < 0 ? "−" : "+";
            button.setAttribute("aria-label", key + " " + delta + " degree");
            button.onclick = () =>
              jobAction("jog", {
                joint: key.replace(".pos", ""),
                delta,
                duration: 1,
              });
            row.append(button);
          }
        }
        $("joints").append(row);
      }
      row.querySelector("strong").textContent =
        value.toFixed(1) + (key === "gripper.pos" ? " %" : "°");
    }
  }
  const signature = JSON.stringify(s.skills);
  if ($("skills").dataset.signature !== signature) {
    $("skills").dataset.signature = signature;
    $("skills").replaceChildren();
    for (const skill of s.skills) {
      const card = document.createElement("div");
      card.className = "skill";
      const title = document.createElement("h3");
      title.textContent = skill.name.replaceAll("_", " ");
      const status = document.createElement("div");
      status.className = "status";
      status.textContent = skill.status;
      const requirements = document.createElement("p");
      requirements.textContent = skill.requires.join(" · ");
      const setup = document.createElement("button");
      setup.textContent = "Setup";
      setup.onclick = () =>
        skillSetup(skill.name).catch((e) => toast(e.message, true));
      const run = document.createElement("button");
      run.textContent = "Preview";
      run.onclick = () => skillParams(skill.name);
      card.append(title, status, requirements, setup, run);
      $("skills").append(card);
    }
  }
  if (s.capability_report)
    $("report").textContent = pretty(s.capability_report);
  const ids =
    s.backend === "hardware"
      ? s.cameras.map((c) => c.id)
      : ["simulation", ...s.cameras.map((c) => c.id)];
  for (const id of ids) {
    let img = id === "simulation" ? $("preview") : $("cam-" + id);
    if (!img) {
      img = document.createElement("img");
      img.id = "cam-" + id;
      img.alt = "Camera " + id;
      $("camera-grid").append(img);
    }
    img.dataset.camera = id;
  }
  if (s.backend === "hardware") $("preview").hidden = true;
  else $("preview").hidden = false;
}
async function updateImages() {
  if (previewBusy || !state) return;
  previewBusy = true;
  try {
    for (const img of document.querySelectorAll(
      "#camera-grid img[data-camera]",
    )) {
      if (img.hidden) continue;
      let response = await fetch(
        "/api/cameras/" + encodeURIComponent(img.dataset.camera) + "/frame",
        { headers: auth ? { Authorization: "Bearer " + auth } : {} },
      );
      if (response.ok) {
        const url = URL.createObjectURL(await response.blob());
        const old = lastImages.get(img.id);
        img.src = url;
        lastImages.set(img.id, url);
        if (old) URL.revokeObjectURL(old);
      }
    }
  } finally {
    previewBusy = false;
  }
}
async function jobAction(path, body = {}) {
  try {
    return await job(await api(path, body));
  } catch (e) {
    toast(e.message, true);
  }
}
act("stop", async () => {
  await api("stop", {});
  toast("Stop latched. Use physical power disconnect in an emergency.");
  await refresh();
});
act("pause", async () => {
  await api("pause", {});
  await refresh();
});
act("resume", async () => {
  await api("resume", {});
  await refresh();
});
act("standby", () => jobAction("standby"));
act("discover", async () => {
  const d = await api("devices");
  $("serial").replaceChildren(new Option("Select follower USB port", ""));
  for (const p of d.serial)
    $("serial").add(new Option(p.port + " — " + p.description, p.port));
  $("calibration").replaceChildren(
    new Option("Select matching calibration", ""),
  );
  for (const c of d.calibrations) {
    let o = new Option(c.robot_id, c.path);
    o.dataset.robotId = c.robot_id;
    o.dataset.digest = c.sha256;
    $("calibration").add(o);
  }
  toast(
    d.serial.length +
      " serial devices; identity alone does not establish follower role",
  );
});
act("connect", async () => {
  const option = $("calibration").selectedOptions[0];
  await api("connect", {
    backend: $("backend").value,
    port: $("serial").value,
    robot_id: option?.dataset.robotId || "",
    calibration_path: $("calibration").value,
    operator_present: $("operator").checked,
  });
  await refresh();
});
act("disconnect", async () => {
  await api("disconnect", {});
  await refresh();
});
act("move-tip", () =>
  jobAction("tip", {
    position: [$("x"), $("y"), $("z")].map((i) => Number(i.value)),
    duration: 2,
  }),
);
act("grip", async () => {
  const draft = await api("gripper/preview", {
    open_fraction: Number($("gripper").value) / 100,
  });
  reviewDraft(draft);
});
function providerConfig() {
  return {
    preset: $("provider").value,
    base_url: $("endpoint").value,
    model: $("model").value,
    share_images: $("share").checked,
  };
}
async function saveProvider() {
  await api("provider", {
    config: providerConfig(),
    api_key: $("api-key").value,
    persist_key: $("persist-key").checked,
  });
  $("api-key").value = "";
  await refresh();
}
act("save-provider", saveProvider);
act("models", async () => {
  await saveProvider();
  const models = await api("models");
  $("model-list").replaceChildren();
  for (const m of models) {
    const option = new Option(
      m.name +
        " · vision " +
        (m.vision ?? "unknown") +
        " · tools " +
        (m.tools ?? "unknown"),
      m.id,
    );
    $("model-list").append(option);
  }
  toast(
    models.length +
      " actual model IDs discovered; capability probe still required",
  );
});
act("probe", async () => {
  await saveProvider();
  await job(await api("provider/probe", {}));
  await refresh();
});
$("provider").onchange = () => {
  $("endpoint").value = presets[$("provider").value].base_url;
  $("model").value = "";
};
act("run-agent", () =>
  jobAction("agent", { objective: $("objective").value, max_steps: 12 }),
);
act("explore", () => jobAction("explore"));
act("find-cameras", async () => {
  const cameras = await api("cameras/discover");
  $("camera-select").replaceChildren(new Option("Select camera", ""));
  for (const camera of cameras)
    $("camera-select").add(new Option("USB camera " + camera.id, camera.id));
  toast(cameras.length + " cameras found");
});
act("open-camera", async () => {
  await api("cameras", {
    camera_id: $("camera-select").value,
    role: $("camera-role").value,
  });
  await refresh();
});
act("commission", async () => {
  const data = await api("commissioning");
  let current = state?.state?.joints || {};
  let option = $("calibration").selectedOptions[0];
  modal(
    "Hardware commissioning",
    data.steps.join("\n"),
    {
      calibrate_command:
        "uv run lerobot-calibrate --robot.type=so101_follower --robot.port=SELECTED_PORT --robot.id=YOUR_ID",
      important:
        "Disconnect the app before motor calibration. Measure every value. Saved profiles never clear Stop.",
    },
    data.profile || {
      robot_id: option?.dataset.robotId || "my_follower",
      port: $("serial").value,
      calibration_sha256: option?.dataset.digest || "",
      safety: {
        joint_limits: Object.fromEntries(
          Object.keys(current).map((k) => [
            k,
            [current[k] - 2, current[k] + 2],
          ]),
        ),
        workspace: { lower: [0.1, -0.1, 0.02], upper: [0.35, 0.1, 0.3] },
        table_z: 0,
        exclusions: [],
      },
      motor_signs: Object.fromEntries(
        [
          "shoulder_pan",
          "shoulder_lift",
          "elbow_flex",
          "wrist_flex",
          "wrist_roll",
        ].map((k) => [k, 1]),
      ),
      motor_offsets: Object.fromEntries(
        [
          "shoulder_pan",
          "shoulder_lift",
          "elbow_flex",
          "wrist_flex",
          "wrist_roll",
        ].map((k) => [k, 0]),
      ),
      tcp: [0, 0, 0],
      standby: current,
      operator_present: false,
      supported_arm: false,
      mapping_verified: false,
      envelope_verified: false,
      camera_id: $("camera-select").value,
    },
    async (value) => {
      await api("commissioning", value);
      toast("Measured commissioning saved. Validate and resume when safe.");
      await refresh();
    },
    "Save measured profile",
  );
});
act("plane", async () => {
  const id = $("camera-select").value;
  if (!id) throw Error("Select and start a camera");
  modal(
    "Register tabletop plane",
    "Measure at least four non-collinear point pairs. Image coordinates are pixels; robot XY and plane Z are metres. Use two different points to check the fit afterward.",
    { step: "fit first, then held-out check", camera_id: id },
    {
      camera_id: id,
      image_points: [
        [100, 100],
        [500, 100],
        [500, 400],
        [100, 400],
      ],
      robot_points: [
        [0.15, -0.08],
        [0.3, -0.08],
        [0.3, 0.08],
        [0.15, 0.08],
      ],
      plane_z: 0,
      max_error_m: 0.003,
    },
    async (value) => {
      const fit = await api("calibration/plane", value);
      $("modal").close();
      modal(
        "Validate independent points",
        "Use at least two measured points that were not used in the fit. Defaults below are only format examples.",
        fit,
        {
          camera_id: id,
          image_points: [
            [250, 200],
            [350, 300],
          ],
          robot_points: [
            [0.20625, -0.026667],
            [0.24375, 0.026667],
          ],
        },
        async (check) => {
          await api("calibration/plane/check", check);
          toast("Independent planar registration passed");
        },
        "Validate measured check points",
      );
    },
    "Fit measured points",
  );
});
async function skillSetup(name) {
  let data;
  try {
    data = await api("skills/" + name + "/setup");
  } catch (e) {
    data = {
      setup: {
        origin: [0.2, 0, 0],
        width: 0.02,
        height: 0.02,
        lift: 0.02,
        orientation: [0, 90, 0],
        tcp_verified: false,
        plane_verified: false,
        measured_on_hardware: false,
      },
    };
  }
  modal(
    name.replaceAll("_", " ") + " setup",
    "Measure these values on your actual installation. Simulation geometry is stored separately. Saving setup invalidates previous readiness.",
    null,
    data.setup,
    async (value) => {
      await api("skills/" + name + "/setup", value);
      toast("Setup saved");
      await refresh();
    },
    "Save setup",
  );
}
function skillParams(name) {
  const params =
    name === "drawing"
      ? { shape: "square" }
      : name === "painting"
        ? { shape: "line" }
        : name === "chess"
          ? { move: "e2e4" }
          : {};
  modal(
    "Plan " + name.replaceAll("_", " "),
    "The entire path is validated before execution. Physical outcomes require inspection afterward.",
    null,
    params,
    async (value) => {
      const draft = await api("skills/preview", { name, params: value });
      $("modal").close();
      reviewDraft(draft);
    },
    "Validate & preview",
  );
}
function reviewDraft(draft) {
  const physical = state.backend === "hardware";
  modal(
    "Review " + draft.skill + " plan",
    "Plan expires in two minutes. Any movement after preview invalidates it.",
    {
      id: draft.id,
      waypoints: draft.requests.length,
      metrics: draft.metrics,
      path: draft.requests,
    },
    null,
    async () => {
      const response = await api("skills/execute", {
        draft_id: draft.id,
        operator_approval: physical && $("approval").checked,
      });
      $("modal").close();
      job(response).catch((e) => toast(e.message, true));
    },
    physical ? "Approve & execute" : "Run simulation",
    physical,
  );
}
function outcomeDialog(result) {
  if (state.backend !== "hardware") return;
  modal(
    "Verify physical outcome",
    "Encoder completion does not establish task success. Inspect the before/after images and actual result. Supply measured evidence.",
    {
      outcome_id: result.id,
      result: result.result,
      metrics: result.metrics,
      before: result.before,
      after: result.after,
    },
    {
      outcome_id: result.id,
      success: false,
      notes: "",
      placement_error_m: null,
    },
    async (value) => {
      await api("skills/verify", value);
      toast("Physical verification recorded");
      await refresh();
    },
    "Record operator verification",
  );
}
function appendEvents(events) {
  for (const event of [...events].reverse()) {
    if (seenEvents.has(event.id)) continue;
    seenEvents.add(event.id);
    const node = document.createElement("div");
    node.className = "event";
    const time = document.createElement("time");
    time.textContent =
      new Date(event.ts * 1000).toLocaleTimeString() + " · " + event.kind;
    const details = document.createElement("pre");
    details.textContent = pretty(event.data);
    node.append(time, details);
    const container = event.kind.startsWith("agent_")
      ? $("activity")
      : $("history");
    container.prepend(node);
    while (container.children.length > 80) container.lastChild.remove();
  }
}
act("export", async () => {
  const response = await fetch("/api/recordings/export", {
    headers: auth ? { Authorization: "Bearer " + auth } : {},
  });
  if (!response.ok) throw Error("Export failed");
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = "so101-episodes.jsonl";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
async function init() {
  try {
    presets = await api("providers");
    for (const key of Object.keys(presets))
      $("provider").add(new Option(key, key));
    await refresh();
    $("provider").value = state.provider.preset;
    $("endpoint").value =
      state.provider.base_url || presets[state.provider.preset].base_url;
    $("model").value = state.provider.model;
    $("share").checked = state.provider.share_images;
    appendEvents(await api("events"));
    const ws = new WebSocket(
      (location.protocol === "https:" ? "wss:" : "ws:") +
        "//" +
        location.host +
        "/ws",
    );
    ws.onopen = () => {
      if (auth) ws.send(JSON.stringify({ token: auth }));
    };
    ws.onmessage = (e) => {
      const data = JSON.parse(e.data);
      state = data.status;
      render(state);
      appendEvents(data.events);
    };
    ws.onclose = () => setTimeout(() => refresh().catch(() => {}), 1000);
    setInterval(() => refresh().catch(() => {}), 3000);
    setInterval(() => updateImages().catch(() => {}), 450);
    setInterval(() => {
      if (
        state?.backend === "hardware" &&
        $("operator").checked &&
        document.visibilityState === "visible"
      )
        api("operator/present", { operator_present: true }).catch(() => {});
    }, 700);
  } catch (e) {
    toast(e.message, true);
  }
}
init();
