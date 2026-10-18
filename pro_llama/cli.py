"""Docker-compose-like host CLI; connects to protected local Unix socket."""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import aiohttp
from .common import config_load

async def request(sock, method, path, data=None):
    connector = aiohttp.UnixConnector(path=sock)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.request(method, "http://localhost" + path, json=data,
                                   headers={"X-Pro-Llama-Request": "1"}, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            text = await resp.text()
            if resp.status >= 400: raise RuntimeError(f"{resp.status}: {text}")
            return json.loads(text) if text else {}

def fmtbytes(v):
    return f"{v / (1024**3):.1f} GiB"

def output(data, json_mode=False):
    print(json.dumps(data, indent=2) if json_mode else data)

def main():
    parser = argparse.ArgumentParser(prog="pro-llama", description="Manage llama-server instances without containers")
    parser.add_argument("--config", default=os.environ.get("PRO_LLAMA_CONFIG", "/etc/prollama-pie/config.json"))
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in ("ps", "status", "models", "scan", "profiles", "scenes", "doctor"):
        sub.add_parser(cmd)
    add = sub.add_parser("model-add"); add.add_argument("id"); add.add_argument("path"); add.add_argument("--hf-repo", default=""); add.add_argument("--card", help="JSON metadata file")
    info = sub.add_parser("model-info"); info.add_argument("id")
    model_import = sub.add_parser("model-import"); model_import.add_argument("json_file")
    fit = sub.add_parser("fit"); fit.add_argument("--profile", default="cpu"); fit.add_argument("--ctx", type=int, default=8192)
    start = sub.add_parser("up", help="launch one instance")
    start.add_argument("name"); start.add_argument("model_id"); start.add_argument("--profile", default="cpu")
    start.add_argument("--port", type=int, dest="public_port")
    for arg in ("ctx-size", "threads", "threads-batch", "gpu-layers", "parallel", "batch-size", "ubatch-size", "draft-tokens"):
        start.add_argument("--" + arg, type=int)
    start.add_argument("--flash-attn", choices=["auto", "on", "off"])
    start.add_argument("--cache-type-k"); start.add_argument("--cache-type-v")
    start.add_argument("--draft-model-id"); start.add_argument("--spec-type")
    start.add_argument("--api-key-file"); start.add_argument("--no-kv-offload", action="store_true")
    start.add_argument("--mlock", action="store_true"); start.add_argument("--no-mmap", action="store_true")
    stop = sub.add_parser("down"); stop.add_argument("name"); stop.add_argument("--force", action="store_true")
    logs = sub.add_parser("logs"); logs.add_argument("name")
    scene = sub.add_parser("scene"); ss = scene.add_subparsers(dest="scene_cmd", required=True)
    sv = ss.add_parser("save-running"); sv.add_argument("name")
    imp = ss.add_parser("import"); imp.add_argument("json_file")
    apply = ss.add_parser("up"); apply.add_argument("name")
    args = parser.parse_args()
    try:
        # CLI only needs socket path; binary may legitimately be temporarily missing.
        cfg = json.loads(Path(args.config).read_text())
        sock = cfg["socket"]
        if args.command in ("ps", "status", "models", "profiles", "scenes", "doctor"):
            data = asyncio.run(request(sock, "GET", "/api/state"))
            if args.command == "ps":
                if args.json: output(data["instances"], True)
                else:
                    print(f"{'NAME':<23} {'MODEL':<22} {'PROFILE':<14} {'HTTPS':<7} {'BACKEND':<8} {'PID':<8} STATUS")
                    for it in data["instances"].values():
                        print(f"{it['name']:<23} {it['model_id'][:21]:<22} {it['profile']:<14} {it['public_port']:<7} {it['backend_port']:<8} {it['pid']:<8} {it['status']}")
            elif args.command == "models":
                if args.json: output(data["models"], True)
                else:
                    for k, v in data["models"].items(): print(f"{k:<30} {v['path']}  {v.get('hf_repo','')}")
            elif args.command == "profiles": output(data["system"]["profiles"], args.json)
            elif args.command == "scenes": output(data["scenes"], args.json)
            elif args.command == "doctor":
                print(f"Management socket: {sock}")
                print(f"Available RAM: {fmtbytes(data['system']['memory']['available'])}")
                for g in data["system"]["gpus"]:
                    print(f"GPU {g['index']} {g['name']} PCI {g['pci']}: {fmtbytes(g['total']-g['used'])} free")
                print("Proxy error:", data.get("last_proxy_error", "none"))
            else: output({"system": data["system"], "instances": data["instances"]}, args.json)
        elif args.command == "scan": output(asyncio.run(request(sock, "POST", "/api/models/scan", {})), args.json)
        elif args.command == "model-add":
            card = json.loads(Path(args.card).read_text()) if args.card else {}
            output(asyncio.run(request(sock, "POST", "/api/models", {"id": args.id, "path": args.path, "hf_repo": args.hf_repo, "card": card})), args.json)
        elif args.command == "model-info": output(asyncio.run(request(sock, "GET", f"/api/models/{args.id}")), args.json)
        elif args.command == "model-import":
            model = json.loads(Path(args.json_file).read_text())
            output(asyncio.run(request(sock, "POST", "/api/models", model)), args.json)
        elif args.command == "fit":
            output(asyncio.run(request(sock, "GET", f"/api/fit?profile={args.profile}&ctx={args.ctx}")), args.json)
        elif args.command == "up":
            keys = ["ctx_size", "threads", "threads_batch", "gpu_layers", "parallel", "batch_size", "ubatch_size", "draft_tokens", "flash_attn", "cache_type_k", "cache_type_v", "draft_model_id", "spec_type", "api_key_file"]
            launch = {k: getattr(args, k) for k in keys if getattr(args, k) is not None}
            for k in ("no_kv_offload", "mlock", "no_mmap"):
                if getattr(args, k): launch["kv_offload" if k == "no_kv_offload" else k] = False if k == "no_kv_offload" else True
            payload = {"name": args.name, "model_id": args.model_id, "profile": args.profile, "launch": launch}
            if args.public_port is not None: payload["public_port"] = args.public_port
            output(asyncio.run(request(sock, "POST", "/api/instances", payload)), args.json)
        elif args.command == "down": output(asyncio.run(request(sock, "POST", f"/api/instances/{args.name}/stop", {"force": args.force})), args.json)
        elif args.command == "logs":
            async def tail():
                conn = aiohttp.UnixConnector(path=sock)
                async with aiohttp.ClientSession(connector=conn) as session:
                    async with session.get(f"http://localhost/api/instances/{args.name}/logs") as r:
                        if r.status >= 400: raise RuntimeError(await r.text())
                        print(await r.text())
            asyncio.run(tail())
        elif args.command == "scene":
            if args.scene_cmd == "save-running":
                payload = {"name": args.name}; url = "/api/scenes/save-running"
            elif args.scene_cmd == "import":
                payload = json.loads(Path(args.json_file).read_text()); url = "/api/scenes"
            else:
                payload = {}; url = f"/api/scenes/{args.name}/apply"
            output(asyncio.run(request(sock, "POST", url, payload)), args.json)
    except (OSError, ValueError, RuntimeError, aiohttp.ClientError) as exc:
        sys.exit(f"pro-llama: {exc}")

if __name__ == "__main__": main()
