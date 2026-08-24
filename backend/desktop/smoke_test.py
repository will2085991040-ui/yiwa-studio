"""YIWA 桌面壳最终冒烟测试（可对 EXE 或 `python -m desktop` 运行）。

用法：
  python desktop/smoke_test.py <launch_cmd...>
  例（对 EXE）：python desktop/smoke_test.py dist\\YIWA.exe
  例（开发态）：python desktop/smoke_test.py --dev

断言项：EXE 启动 / /health / 数据目录 / SQLite / migration / 前端页面 /
        创建 Project / 至少一次 AI 创作 / Play Runtime / 重启数据保留。
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

PORT = 8897
_TOKEN = ""  # 强制登录模式的 Bearer 缓存（_login_smoke 填充）
EXPECTED_REVISION = "0014_user"
REQUIRED_TABLES = [
    "projects", "agent_specs", "agent_versions", "agent_runs", "agent_steps",
    "prompt_definitions", "prompt_versions", "artifacts", "player_sessions",
    "memory_entries", "action_proposals", "skills", "branches", "branch_versions",
    "materials", "play_sessions", "play_turns", "alembic_version",
]


def http(method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if _TOKEN:
        req.add_header("Authorization", f"Bearer {_TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            content = resp.read().decode("utf-8")
            return resp.status, (json.loads(content) if content else {})
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def _login_smoke(base: str) -> None:
    """强制登录模式下，先注册并缓存 token，保证后续受保护接口 401 不再阻塞冒烟流程。

    register/login 是 public 端点；开发态（AUTH_REQUIRED=false）注册同样可用，token 会被静默携带。
    """
    global _TOKEN
    _TOKEN = ""
    try:
        status, reg = http("POST", f"{base}/api/auth/register",
                           {"username": "smoke_user", "password": "smoke-pass-1"})
        if status in (200, 201):
            _TOKEN = reg.get("token", "") or ""
            return
        status, log = http("POST", f"{base}/api/auth/login",
                           {"username": "smoke_user", "password": "smoke-pass-1"})
        if status in (200, 201):
            _TOKEN = log.get("token", "") or ""
    except Exception:
        _TOKEN = ""


def get_text(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def wait_health(base: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, body = http("GET", f"{base}/health")
            if status == 200 and body.get("status") == "ok":
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("服务未在超时时间内就绪（/health）")


def start_proc(cmd: list[str], cwd: str) -> subprocess.Popen:
    return subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )


def kill_tree(proc: subprocess.Popen) -> None:
    """结束整个进程树：PyInstaller onefile 会 fork 子进程，terminate() 只杀 bootloader。"""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def run(launch_cmd: list[str], cwd: str) -> dict:
    data_dir = tempfile.mkdtemp(prefix="yiwa-smoke-")
    base = f"http://127.0.0.1:{PORT}"
    results: dict[str, bool] = {}

    def step(name: str, ok: bool, extra: str = "") -> None:
        results[name] = ok
        print(f"  [{'OK' if ok else 'FAIL'}] {name} {extra}")

    proc = start_proc(launch_cmd + ["--data-dir", data_dir, "--port", str(PORT), "--no-browser"], cwd)
    try:
        wait_health(base)
        _login_smoke(base)  # 生产模式强制登录：注册 smoke 用户并缓存 token
        status, health = http("GET", f"{base}/health")
        step("health", status == 200 and health.get("status") == "ok", str(health))

        # 数据目录 + 配置
        step("data_dir", os.path.isdir(os.path.join(data_dir, "projects")))
        step("config_json", os.path.isfile(os.path.join(data_dir, "config.json")))

        # 前端页面可访问
        code, html = get_text(f"{base}/")
        step("frontend_page", code == 200 and "YIWA" in html, f"status={code}")

        # SQLite + migration（直接读 sqlite 文件）
        db_path = os.path.join(data_dir, "yiwa.db")
        step("sqlite_ok", os.path.isfile(db_path) and os.path.getsize(db_path) > 0)
        import sqlite3

        con = sqlite3.connect(db_path)
        try:
            rev = con.execute("select version_num from alembic_version").fetchone()[0]
            tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        finally:
            con.close()
        step("migration", rev == EXPECTED_REVISION, f"rev={rev}")
        step("tables", set(REQUIRED_TABLES) <= tables, f"missing={sorted(set(REQUIRED_TABLES) - tables)}")

        # 创建 Project（Golden Path 入口）
        status, created = http(
            "POST", f"{base}/api/director/plan", {"goal": "制作一个乙女悬疑Galgame，女主进入娱乐公司"},
        )
        pid = created.get("project_id")
        step("create_project", status in (200, 201) and bool(pid), f"status={status} pid={pid}")

        # 至少一次 AI 创作操作（mock LLM 编排产出 artifacts）
        status, orch = http("POST", f"{base}/api/orchestrate/{pid}")
        artifacts = orch.get("artifacts", [])
        step("ai_create_op", status == 200 and len(artifacts) > 0, f"status={status} artifacts={len(artifacts)}")

        # Play Runtime 可启动
        status, ps = http("POST", f"{base}/api/projects/{pid}/play/sessions")
        sid = ps.get("id")
        status2, turn = http(
            "POST", f"{base}/api/projects/{pid}/play/sessions/{sid}/turn",
            {"intent": "询问线索", "mutation": {"operations": [{"op": "add_evidence", "name": "旧钥匙"}]}},
        )
        step("runtime_start", status == 200 and bool(sid) and status2 == 200 and turn.get("seq") == 1)

        # 增量：模型设置 / 媒体生成 / 世界图试玩 / HTML 导出
        scode, shtml = get_text(f"{base}/settings")
        step("settings_page", scode == 200 and "模型设置" in shtml, f"status={scode}")
        wcode, _ = get_text(f"{base}/worldplay")
        step("worldplay_page", wcode == 200, f"status={wcode}")
        status, sconf = http("GET", f"{base}/api/settings")
        step("settings_api", status == 200 and "values" in sconf and "yiwa_ready" in sconf.get("ready", {}),
             f"status={status}")
        status, img = http("POST", f"{base}/api/projects/{pid}/images", {"prompt": "冒烟测试立绘"})
        step("media_image", status == 200 and img.get("provider") == "mock", f"status={status}")
        status, wpar = http(
            "POST", f"{base}/api/projects/{pid}/worldplay/start", {"kind": "open_world", "title": "冒烟"},
        )
        wpid = wpar.get("play_id")
        status2, wstep = http(
            "POST", f"{base}/api/projects/{pid}/worldplay/{wpid}/step",
            {
                "raw_input": "探看",
                "mutation": {
                    "event_id": "e1", "turn": 1, "action_kind": "look",
                    "entities": {"upsert": [{"id": "r1", "type": "location", "label": "房间"}]},
                    "edges": {"upsert": [], "expire": []},
                    "state_slots": {"upsert": []},
                    "evidence": {"transitions": []},
                },
            },
        )
        step("worldplay_run", status == 200 and bool(wpid) and status2 == 200
             and wstep.get("world", {}).get("turn") == 1, f"status={status}")

        # 增量：小说导入 -> 拆剧本 -> 角色卡 -> 人物关系 -> 串联互动图
        sample = "林烬说：这场雨不会停了。\n\n苏晚问：你还在等谁？\n\n林烬说：等一个不该等的人。\n\n" * 6
        status, imp = http("POST", f"{base}/api/novel/import", {
            "title": "冒烟小说", "text": sample, "game_type": "avg",
        })
        step("novel_import", status == 201 and bool(imp.get("project_id"))
             and imp.get("scene_count", 0) >= 1 and bool(imp.get("characters")), f"status={status}")

        return {"data_dir": data_dir, "results": results, "pid": pid}
    finally:
        kill_tree(proc)


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python desktop/smoke_test.py <exe或--dev>")
        return 2
    backend = str(Path(__file__).resolve().parents[1])
    dev = sys.argv[1] == "--dev"
    launch_cmd = [sys.executable, "-m", "desktop"] if dev else [sys.argv[1]]

    print("== First run ==")
    first = run(launch_cmd, backend)
    print("== Restart (persistence) ==")
    proc = start_proc(
        launch_cmd + ["--data-dir", first["data_dir"], "--port", str(PORT), "--no-browser"], backend,
    )
    try:
        base = f"http://127.0.0.1:{PORT}"
        wait_health(base)
        status, projects = http("GET", f"{base}/api/projects")
        persisted = status == 200 and any(p.get("goal", "").startswith("制作") for p in projects)
        print(f"  [{'OK' if persisted else 'FAIL'}] restart_persistence status={status}")
        first["results"]["restart_persistence"] = persisted
    finally:
        kill_tree(proc)

    failed = [k for k, v in first["results"].items() if not v]
    print("\n== Summary ==")
    for k, v in first["results"].items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    print(f"\n{'ALL PASS' if not failed else 'FAILED: ' + ', '.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())