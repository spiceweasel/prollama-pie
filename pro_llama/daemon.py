"""Authenticated HTTP dashboard/API plus local Unix-domain CLI API."""
import argparse
import asyncio
import base64
import hmac
import fcntl
import os
import signal
import socket
import sys
from pathlib import Path

from aiohttp import web
from .common import config_load, name
from .supervisor import Supervisor

ROOT = Path(__file__).parent / "static"
SUP = web.AppKey("supervisor", Supervisor)
CONFIG = web.AppKey("configuration", dict)

def authorize(request):
    # Unix socket is protected by filesystem permissions; no TCP bypass.
    sk = request.transport.get_extra_info("socket") if request.transport else None
    if sk and sk.family == socket.AF_UNIX:
        return True
    cfg = request.app[CONFIG]
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "): return False
    try:
        raw = base64.b64decode(header[6:], validate=True).decode("utf-8")
        user, password = raw.split(":", 1)
        expected = Path(cfg["admin_password_file"]).read_text().strip()
        return hmac.compare_digest(user, cfg["admin_username"]) and hmac.compare_digest(password, expected)
    except (ValueError, OSError, UnicodeError):
        return False

@web.middleware
async def auth_middleware(req, handler):
    if not authorize(req):
        raise web.HTTPUnauthorized(headers={"WWW-Authenticate": 'Basic realm="prollama-pie"'})
    if req.method not in ("GET", "HEAD", "OPTIONS"):
        # JSON + custom header stop ordinary cross-site form posts. Same-origin
        # Origin is additionally required when a browser supplies it.
        if req.headers.get("X-Pro-Llama-Request") != "1":
            raise web.HTTPForbidden(text="missing X-Pro-Llama-Request header")
        origin = req.headers.get("Origin")
        if origin:
            from urllib.parse import urlsplit
            uri = urlsplit(origin)
            host = req.headers.get("Host", "")
            if uri.netloc != host or uri.scheme not in ("http", "https"):
                raise web.HTTPForbidden(text="cross-origin request denied")
    try:
        return await handler(req)
    except (ValueError, KeyError, TypeError) as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc

async def body(req):
    obj = await req.json()
    if not isinstance(obj, dict): raise ValueError("expected JSON object")
    return obj

async def home(req): return web.FileResponse(ROOT / "index.html")
async def static(req):
    fname = req.match_info["filename"]
    if fname not in ("app.js", "style.css"): raise web.HTTPNotFound()
    return web.FileResponse(ROOT / fname)
async def get_state(req): return web.json_response(req.app[SUP].snapshot())
async def scan(req): return web.json_response({"added": req.app[SUP].scan()})
async def add_model(req): return web.json_response(req.app[SUP].add_model(await body(req)))
async def model_detail(req): return web.json_response(req.app[SUP].model_info(req.match_info["id"]))
async def estimate(req):
    return web.json_response(req.app[SUP].fit(req.query.get("profile", "cpu"), int(req.query.get("ctx", "8192")),
                                                req.query.get("k", "f16"), req.query.get("v", "f16")))
async def start(req): return web.json_response(await req.app[SUP].start(await body(req)))
async def stop(req):
    obj = await body(req)
    return web.json_response(await req.app[SUP].stop(req.match_info["id"], force=obj.get("force") is True))
async def save_scene(req): return web.json_response({"name": req.app[SUP].save_scene(await body(req))})
async def scene_running(req):
    data = await body(req)
    return web.json_response({"name": req.app[SUP].save_running_scene(data["name"])})
async def scene_apply(req): return web.json_response({"launched": await req.app[SUP].apply_scene(req.match_info["id"])})
async def logs(req):
    item = req.app[SUP].state["instances"].get(name(req.match_info["id"]))
    if item is None: raise web.HTTPNotFound()
    with open(item["log"], "rb") as f:
        f.seek(0, 2); f.seek(max(0, f.tell() - 24000)); chunk = f.read()
    return web.Response(text=chunk.decode("utf-8", "replace"), content_type="text/plain")

def make_app(cfg, sup):
    app = web.Application(middlewares=[auth_middleware], client_max_size=1024*1024)
    app[CONFIG] = cfg; app[SUP] = sup
    app.add_routes([web.get("/", home), web.get("/static/{filename}", static),
                    web.get("/api/state", get_state), web.post("/api/models/scan", scan),
                    web.post("/api/models", add_model), web.get("/api/models/{id}", model_detail),
                    web.get("/api/fit", estimate), web.post("/api/instances", start),
                    web.post("/api/instances/{id}/stop", stop), web.post("/api/scenes", save_scene),
                    web.post("/api/scenes/save-running", scene_running),
                    web.post("/api/scenes/{id}/apply", scene_apply), web.get("/api/instances/{id}/logs", logs)])
    return app

async def run(cfg):
    # Explicit single-writer lock even if two manual daemon starts race.
    lock_path = Path(cfg["state_dir"]) / ".daemon.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(lock_path, "a+")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_fd.close()
        raise RuntimeError("a supervisor already holds the state-directory lock")
    sup = Supervisor(cfg)
    sup.scan()
    app = make_app(cfg, sup)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    unix_path = Path(cfg["socket"])
    unix_path.parent.mkdir(parents=True, exist_ok=True)
    unix_path.unlink(missing_ok=True)
    u = web.UnixSite(runner, str(unix_path)); await u.start()
    os.chmod(unix_path, 0o660)
    tcp = web.TCPSite(runner, cfg.get("admin_host", "127.0.0.1"), cfg["admin_port"])
    await tcp.start()
    # Apply admin listen config and restore live routes after supervisor restarts.
    sup._apply_proxy_if_changed()
    task = asyncio.create_task(sup.run_poll())
    try:
        await asyncio.Event().wait()
    finally:
        task.cancel()
        await runner.cleanup()
        unix_path.unlink(missing_ok=True)
        lock_fd.close()

def main():
    parser = argparse.ArgumentParser(description="prollama-pie supervisor")
    parser.add_argument("--config", default=os.environ.get("PRO_LLAMA_CONFIG", "/etc/prollama-pie/config.json"))
    args = parser.parse_args()
    cfg = config_load(args.config)
    try: asyncio.run(run(cfg))
    except KeyboardInterrupt: pass

if __name__ == "__main__": main()
