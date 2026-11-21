from fastapi.testclient import TestClient
from so101_lab.server.api import create_app

HEADERS = {"X-Lab-Request": "1"}


def test_dashboard_controls_and_csrf(tmp_path):
    with TestClient(create_app(tmp_path, realtime=False)) as client:
        assert client.get("/").status_code == 200
        assert "SO-101 Autonomy Lab" in client.get("/").text
        state = client.get("/api/status").json()
        assert state["backend"] == "simulation" and len(state["state"]["joints"]) == 6
        assert client.post("/api/stop", json={}).status_code == 403
        assert (
            client.post(
                "/api/stop", json={}, headers={**HEADERS, "Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert client.post("/api/stop", json={}, headers=HEADERS).json()["ok"]
        assert client.get("/api/status").json()["stopped"]
        assert client.post("/api/resume", json={}, headers=HEADERS).json()["ok"]
        assert client.get("/api/cameras/simulation/frame").headers["content-type"] == "image/jpeg"
        draft = client.post("/api/gripper/preview", json={"open_fraction": 0.5}, headers=HEADERS).json()
        assert draft["requests"][0]["joints"]["gripper.pos"] == 50
        assert client.get("/api/recordings/export").status_code == 200


def test_model_keys_are_never_returned(tmp_path):
    with TestClient(create_app(tmp_path, realtime=False)) as client:
        body = {"config": {"preset": "openai", "model": "real-id"}, "api_key": "do-not-echo-secret"}
        response = client.post("/api/provider", json=body, headers=HEADERS)
        assert response.status_code == 200
        assert "do-not-echo-secret" not in response.text
        assert "do-not-echo-secret" not in client.get("/api/status").text
        assert "do-not-echo-secret" not in client.get("/api/events").text
        assert (
            client.post("/api/jog", json={"joint": "gripper", "delta": 1}, headers=HEADERS).status_code == 400
        )


def test_remote_auth_and_websocket_origin(tmp_path):
    with TestClient(create_app(tmp_path, realtime=False, remote_token="x" * 32)) as client:
        assert client.get("/api/status").status_code == 401
        assert client.get("/api/status", headers={"Authorization": "Bearer " + "x" * 32}).status_code == 200
        assert client.get("/", headers={"Host": "other.example"}).status_code == 200


def test_invalid_secret_submission_is_not_echoed(tmp_path):
    with TestClient(create_app(tmp_path, realtime=False)) as client:
        key = "private-invalid-key-" * 300
        response = client.post(
            "/api/provider", json={"config": {"preset": "openai"}, "api_key": key}, headers=HEADERS
        )
        assert response.status_code == 422
        assert "private-invalid-key" not in response.text
        assert "input" not in response.json()["detail"][0]
