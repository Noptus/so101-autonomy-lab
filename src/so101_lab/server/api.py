from __future__ import annotations

import asyncio
import hmac
import os
import time
import uuid
from contextlib import asynccontextmanager
from importlib.resources import files
from urllib.parse import urlparse

import cv2
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from so101_lab.agents.providers import PRESETS, Provider, ProviderConfig
from so101_lab.domain import Commissioning, Validated
from so101_lab.lab import Lab
from so101_lab.perception.calibration import PlaneRegistration, detect_markers, intrinsics, validate_plane
from so101_lab.recording.episodes import export_jsonl
from so101_lab.robot.calibration import calibrations
from so101_lab.skills.planners import SkillSetup


class Connect(Validated):
    backend: str = "simulation"
    port: str = ""
    robot_id: str = ""
    calibration_path: str = ""
    operator_present: bool = False


class ProviderRequest(Validated):
    config: ProviderConfig
    api_key: str = Field(default="", repr=False, max_length=4096)
    persist_key: bool = False


class Jog(Validated):
    joint: str
    delta: float = Field(ge=-3, le=3)
    duration: float = Field(default=1, ge=0.5, le=10)


class Tip(Validated):
    position: tuple[float, float, float]
    orientation: tuple[float, float, float] | None = None
    duration: float = Field(default=2, ge=0.5, le=20)


class SkillRequest(Validated):
    name: str
    params: dict = Field(default_factory=dict)


class Approval(Validated):
    draft_id: str
    operator_approval: bool = False


class Verification(Validated):
    outcome_id: str
    success: bool
    notes: str = Field(max_length=2000)
    placement_error_m: float | None = Field(default=None, ge=0, le=1)


class CameraRequest(Validated):
    camera_id: str
    role: str = "overhead"


class AgentRequest(Validated):
    objective: str = Field(min_length=1, max_length=4000)
    max_steps: int = Field(default=12, ge=1, le=20)


class PlaneCheck(Validated):
    camera_id: str
    image_points: list[tuple[float, float]]
    robot_points: list[tuple[float, float]]


class IntrinsicsRequest(Validated):
    camera_id: str
    object_points: list[list[tuple[float, float, float]]]
    image_points: list[list[tuple[float, float]]]
    image_size: tuple[int, int]


def create_app(data_dir=None, realtime=True, remote_token=None):
    token = remote_token or os.getenv("SO101_REMOTE_TOKEN", "")
    lab = Lab(data_dir or os.getenv("SO101_DATA_DIR", ".so101-lab"), realtime=realtime)
    jobs, active = {}, set()
    app_tasks = set()

    @asynccontextmanager
    async def lifespan(app):
        # Single worker only: never start multiple controller processes.
        from filelock import FileLock

        ownership = FileLock(str(lab.directory / "owner.lock"))
        ownership.acquire(timeout=0)
        # Restore only explicitly selected cameras. Hardware is never auto-connected.
        for item in lab.memory.get("cameras", []):
            try:
                await asyncio.to_thread(lab.cameras.open, item["camera_id"], item["role"])
            except ValueError:
                lab.memory.add("camera_fault", {"camera_id": item["camera_id"]})
        try:
            yield
        finally:
            lab.supervisor.stop()
            for task in list(app_tasks):
                task.cancel()
            if app_tasks:
                await asyncio.gather(*list(app_tasks), return_exceptions=True)
            # Stop is already latched; wait for any threaded motion to observe it.
            deadline = time.monotonic() + 3
            while lab.controller.busy.locked() and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            await asyncio.to_thread(lab.close)
            ownership.release()

    app = FastAPI(title="SO-101 Autonomy Lab", version="0.1.0", lifespan=lifespan)
    app.state.lab = lab
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*"] if token else ["127.0.0.1", "localhost", "[::1]", "testserver"],
    )

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-origin requests are disabled"}, status_code=403)
        if request.url.path.startswith("/api/"):
            if token and not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
                return JSONResponse({"detail": "Remote authentication required"}, status_code=401)
            if request.method not in ("GET", "HEAD") and request.headers.get("x-lab-request") != "1":
                return JSONResponse({"detail": "Missing local request header"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Validation errors must not echo submitted secrets through Pydantic input fields.
        return JSONResponse(
            {"detail": [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]},
            status_code=422,
        )

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": lab.memory.clean(str(exc))}, status_code=400)

    @app.exception_handler(ConnectionError)
    async def disconnected(request, exc):
        return JSONResponse(
            {"detail": "Robot disconnected; validate and reconnect without resuming motion"}, status_code=409
        )

    def start_job(function, *args, coroutine=False):
        if active or lab.supervisor.running or lab.operation_active:
            raise HTTPException(409, "Another operation is active; Stop remains available")
        job_id = uuid.uuid4().hex
        jobs[job_id] = {"id": job_id, "status": "running"}
        active.add(job_id)

        async def run():
            try:
                result = await function(*args) if coroutine else await asyncio.to_thread(function, *args)
                jobs[job_id] = {"id": job_id, "status": "complete", "result": lab.memory.clean(result)}
            except Exception as exc:
                jobs[job_id] = {"id": job_id, "status": "failed", "error": lab.memory.clean(str(exc))}
                lab.memory.add("job_error", {"message": str(exc)})
            finally:
                active.discard(job_id)
                while len(jobs) > 50:
                    jobs.pop(next(iter(jobs)))

        task = asyncio.create_task(run())
        app_tasks.add(task)
        task.add_done_callback(app_tasks.discard)
        return jobs[job_id]

    @app.get("/favicon.ico")
    async def favicon():
        return Response(status_code=204)

    @app.get("/")
    async def home():
        return FileResponse(files("so101_lab").joinpath("ui/index.html"))

    @app.get("/assets/{name}")
    async def asset(name: str):
        if name not in ("app.js", "style.css"):
            raise HTTPException(404)
        return FileResponse(files("so101_lab").joinpath("ui", name))

    @app.get("/api/status")
    async def status():
        return await asyncio.to_thread(lab.status)

    @app.get("/api/devices")
    async def devices():
        return {"serial": await asyncio.to_thread(lab.serial_devices), "calibrations": calibrations()}

    @app.post("/api/connect")
    async def connect(body: Connect):
        if active:
            raise HTTPException(409, "An operation is active")
        return await asyncio.to_thread(lab.connect, **body.model_dump())

    @app.post("/api/disconnect")
    async def disconnect():
        return await asyncio.to_thread(lab.disconnect)

    @app.post("/api/stop")
    @app.post("/api/pause")
    async def stop():
        lab.supervisor.stop()
        return {
            "ok": True,
            "message": "Stop latched independently of the model. Physical power disconnect remains necessary in an emergency.",
        }

    @app.post("/api/operator/present")
    async def operator_present(body: dict):
        if body.get("operator_present") is not True:
            lab.controller.stop()
            raise ValueError("Operator must actively supervise hardware")
        lab.operator_seen = time.monotonic()
        return {"ok": True}

    @app.post("/api/resume")
    async def resume():
        if active:
            raise HTTPException(409, "Wait for the stopped operation to finish")
        await asyncio.to_thread(lab.controller.resume)
        return {"ok": True, "message": "State validated; motion can be requested again"}

    @app.post("/api/jog")
    async def jog(body: Jog):
        from so101_lab.domain import ARM

        if body.joint not in ARM:
            raise ValueError("Choose one of the five positioning joints")
        return start_job(lambda: lab.call_tool("move_joint_delta", body.model_dump()))

    @app.post("/api/tip")
    async def tip(body: Tip):
        return start_job(
            lambda: lab.controller.move_tip(body.position, body.orientation, body.duration).model_dump()
        )

    @app.post("/api/gripper")
    async def gripper(body: dict):
        from so101_lab.agents.tools import Gripper

        args = Gripper.model_validate(body)
        # Physical gripper control uses an exact-plan preview and approval, like contact skills.
        if lab.robot.hardware:
            raise ValueError("Use a commissioned contact skill to approve physical gripper motion")
        return start_job(lambda: lab.controller.set_gripper(args.open_fraction).model_dump())

    @app.post("/api/gripper/preview")
    async def gripper_preview(body: dict):
        from so101_lab.agents.tools import Gripper

        args = Gripper.model_validate(body)
        if active:
            raise ValueError("Wait for the active operation")
        return await asyncio.to_thread(lab.draft_gripper, args.open_fraction)

    @app.post("/api/standby")
    async def standby():
        if not lab.robot.hardware:
            target = (
                __import__("so101_lab.robot.simulator", fromlist=["SimulatedRobot"]).SimulatedRobot().joints
            )
        else:
            profile = lab.memory.get("commissioning")
            if not profile:
                raise ValueError("No verified standby pose is saved")
            target = profile["standby"]
        return start_job(lambda: lab.controller.move_joints(target, 3).model_dump())

    @app.get("/api/commissioning")
    async def commissioning():
        return {
            "profile": lab.memory.get("commissioning"),
            "schema": Commissioning.model_json_schema(),
            "steps": [
                "Support the arm, inspect power disconnect and select the follower USB port",
                "Run official LeRobot motor calibration in a terminal while the app is disconnected",
                "Start a camera and measure motor signs, offsets, TCP, table plane and exclusion zones",
                "Save the profile with the actual measured standby pose; validate and resume",
                "Jog one degree in a clear envelope, compare camera/encoders and test Stop",
                "Commission each contact skill and approve its exact plan separately",
            ],
        }

    @app.post("/api/commissioning")
    async def commissioning_save(body: Commissioning):
        if active:
            raise ValueError("Wait for the active operation")
        await asyncio.to_thread(lab.apply_commissioning, body)
        return {"ok": True, "message": "Profile saved; existing Stop remains latched"}

    @app.get("/api/cameras/discover")
    async def cameras_discover():
        if active:
            raise ValueError("Stop motion before probing additional cameras")
        return await asyncio.to_thread(lab.cameras.discover)

    @app.post("/api/cameras")
    async def camera_open(body: CameraRequest):
        if active:
            raise ValueError("Wait for the active operation before changing cameras")
        await asyncio.to_thread(lab.cameras.open, body.camera_id, body.role)
        lab.memory.save("cameras", [{"camera_id": c["id"], "role": c["role"]} for c in lab.cameras.status()])
        return {"ok": True}

    @app.get("/api/cameras/{camera_id}/frame")
    async def camera_frame(camera_id: str):
        image = await asyncio.to_thread(lab.preview_frame, camera_id)
        ok, buf = cv2.imencode(".jpg", image)
        if not ok:
            raise ValueError("Cannot encode frame")
        return Response(buf.tobytes(), media_type="image/jpeg")

    @app.get("/api/cameras/{camera_id}/markers")
    async def markers(camera_id: str):
        return detect_markers(await asyncio.to_thread(lab.frame, camera_id))

    @app.post("/api/calibration/plane")
    async def register_plane(body: PlaneRegistration):
        lab.idle()
        result = body.solve()
        lab.memory.save(f"plane:{body.camera_id}", result)
        return result

    @app.post("/api/calibration/plane/check")
    async def check_plane(body: PlaneCheck):
        lab.idle()
        registration = lab.memory.get(f"plane:{body.camera_id}")
        if not registration:
            raise ValueError("Fit a plane registration first")
        result = validate_plane(registration, body.image_points, body.robot_points)
        lab.memory.save(f"plane:{body.camera_id}", result)
        return result

    @app.post("/api/calibration/intrinsics")
    async def camera_intrinsics(body: IntrinsicsRequest):
        lab.idle()
        result = await asyncio.to_thread(intrinsics, body.object_points, body.image_points, body.image_size)
        lab.memory.save(f"intrinsics:{body.camera_id}", result)
        return result

    @app.get("/api/providers")
    async def providers():
        return {
            k: {"protocol": v[0], "base_url": v[1], "environment_variable": v[2]} for k, v in PRESETS.items()
        }

    @app.post("/api/provider")
    async def configure(body: ProviderRequest):
        if active:
            raise ValueError("Wait for the active operation")
        return lab.configure_provider(body.config, body.api_key, body.persist_key)

    @app.get("/api/models")
    async def models():
        provider = Provider(lab.provider_config, lab.secrets.get(lab.provider_config))
        try:
            return await provider.models()
        except Exception as exc:
            raise ValueError(str(exc)) from exc

    @app.post("/api/provider/probe")
    async def probe():
        async def run():
            config = lab.provider_config
            identity = lab.provider_identity()
            result = await Provider(config, lab.secrets.get(config)).probe()
            lab.memory.save("provider_probe", {"identity": identity, "time": time.time(), "result": result})
            return result

        return start_job(run, coroutine=True)

    @app.post("/api/agent")
    async def agent(body: AgentRequest):
        return start_job(lab.supervisor.run, body.objective, body.max_steps, coroutine=True)

    @app.post("/api/explore")
    async def explore():
        return start_job(lab.explorer.run)

    @app.post("/api/skills/preview")
    async def skill_preview(body: SkillRequest):
        if active:
            raise ValueError("Wait for the active operation")
        return await asyncio.to_thread(lab.draft_skill, body.name, body.params)

    @app.post("/api/skills/execute")
    async def skill_execute(body: Approval):
        return start_job(lab.execute_draft, body.draft_id, body.operator_approval)

    @app.get("/api/skills/{skill}/setup")
    async def skill_setup(skill: str):
        return {"setup": lab.setup_for(skill).model_dump(), "schema": SkillSetup.model_json_schema()}

    @app.post("/api/skills/{skill}/setup")
    async def skill_setup_save(skill: str, body: SkillSetup):
        if active:
            raise ValueError("Wait for the active operation")
        lab.save_skill_setup(skill, body)
        return {"ok": True}

    @app.post("/api/skills/verify")
    async def verify(body: Verification):
        return lab.verify_outcome(body.outcome_id, body.success, body.notes, body.placement_error_m)

    @app.get("/api/jobs/{job_id}")
    async def job(job_id: str):
        if job_id not in jobs:
            raise HTTPException(404)
        return jobs[job_id]

    @app.get("/api/events")
    async def events(after: int = 0, limit: int = 100):
        return lab.memory.events(limit, after)

    @app.get("/api/recordings/export")
    async def export():
        return StreamingResponse(
            export_jsonl(lab.memory),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": 'attachment; filename="so101-episodes.jsonl"'},
        )

    @app.get("/api/observations/{filename}")
    async def observation(filename: str):
        if not filename.endswith(".jpg") or any(
            c not in "abcdefghijklmnopqrstuvwxyz0123456789-." for c in filename
        ):
            raise HTTPException(404)
        path = lab.directory / "observations" / filename
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path)

    @app.websocket("/ws")
    async def stream(websocket: WebSocket):
        origin = websocket.headers.get("origin")
        host = websocket.headers.get("host", "")
        if (
            not origin
            or urlparse(origin).netloc != host
            or (not token and urlparse("//" + host).hostname not in ("127.0.0.1", "localhost", "::1"))
        ):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            if token:
                auth = await asyncio.wait_for(websocket.receive_json(), 5)
                if not hmac.compare_digest(auth.get("token", ""), token):
                    await websocket.close(code=1008)
                    return
            cursor = 0
            while True:
                events = lab.memory.events(100, cursor)
                if events:
                    cursor = max(e["id"] for e in events)
                await websocket.send_json({"status": await asyncio.to_thread(lab.status), "events": events})
                await asyncio.sleep(0.5)
        except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
            return

    return app
