"""Single-writer supervisor for model instances and nginx route reconciliation."""
import asyncio
import copy
import datetime as dt
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

import aiohttp
import psutil

from .common import allowed_ports, atomic_json, can_bind, name, port, read_json
from .gguf import disk_size, estimate_kv, metadata
from .hardware import gpus, memory, GIB

DTYPE = {"f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "q5_0", "q5_1", "iq4_nl"}
FLASH = {"auto", "on", "off"}
CONTROLLED_FLAGS = {"--host", "--port", "--model", "-m", "--api-key", "--api-key-file",
                    "--alias", "-a", "--metrics", "--no-metrics", "--ssl-cert-file", "--ssl-key-file",
                    "-p", "--model-url", "--hf-repo", "--models-dir", "--models-preset",
                    "--api-key-file", "--model-draft", "-md"}

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def valid_running(item):
    try:
        p = psutil.Process(item["pid"])
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE and abs(p.create_time() - item["created_at"]) < 0.02
    except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
        return False

def config_for_instance(config, models, spec):
    model_id = name(spec["model_id"])
    profile_name = name(spec.get("profile", "cpu"))
    if model_id not in models:
        raise ValueError("unknown model")
    if profile_name not in config["profiles"]:
        raise ValueError("unknown hardware profile")
    model = models[model_id]
    if not Path(model["path"]).is_file():
        raise ValueError("model file missing")
    prof = config["profiles"][profile_name]
    launch = copy.deepcopy(model.get("launch", {}))
    launch.update(spec.get("launch", {}))
    def integer(k, default, lo=0, hi=1000000):
        v = launch.get(k, default)
        if type(v) is not int or not lo <= v <= hi:
            raise ValueError(f"{k} must be integer {lo}..{hi}")
        return v
    ctx = integer("ctx_size", 8192, 1, 1048576)
    ngl = integer("gpu_layers", 99 if prof["gpu_ids"] else 0, 0, 999)
    if not prof["gpu_ids"] and ngl != 0:
        raise ValueError("CPU-only profile requires gpu_layers=0")
    threads = integer("threads", max(1, (os.cpu_count() or 8) // 2), 1, 1024)
    threads_batch = integer("threads_batch", threads, 1, 1024)
    batch = integer("batch_size", 2048, 1, 262144)
    ubatch = integer("ubatch_size", 512, 1, 262144)
    parallel = integer("parallel", 1, 1, 512)
    flash = launch.get("flash_attn", "auto")
    ck, cv = launch.get("cache_type_k", "f16"), launch.get("cache_type_v", "f16")
    if flash not in FLASH or ck not in DTYPE or cv not in DTYPE:
        raise ValueError("invalid flash attention or KV cache type")
    normalized = {"ctx_size": ctx, "gpu_layers": ngl, "threads": threads, "threads_batch": threads_batch,
                  "batch_size": batch, "ubatch_size": ubatch, "parallel": parallel, "flash_attn": flash,
                  "cache_type_k": ck, "cache_type_v": cv, "kv_offload": launch.get("kv_offload", True),
                  "mlock": launch.get("mlock", False), "no_mmap": launch.get("no_mmap", False),
                  "jinja": launch.get("jinja", True), "draft_model_id": launch.get("draft_model_id"),
                  "spec_type": launch.get("spec_type", "none"),
                  "draft_tokens": integer("draft_tokens", 4, 1, 64),
                  "api_key_file": launch.get("api_key_file") or config.get("default_model_api_key_file"), "extra_args": launch.get("extra_args", [])}
    for key in ("kv_offload", "mlock", "no_mmap", "jinja"):
        if type(normalized[key]) is not bool:
            raise ValueError(f"{key} must be boolean")
    draft = normalized["draft_model_id"]
    if draft is not None and draft not in models:
        raise ValueError("unknown draft model")
    if draft is not None and not Path(models[draft]["path"]).is_file():
        raise ValueError("draft model file missing")
    if normalized["spec_type"] not in {"none", "draft-simple", "ngram-simple", "ngram-cache", "ngram-mod", "ngram-map-k", "ngram-map-k4v", "draft-eagle3", "draft-mtp", "draft-dflash", "draft-dspark"}:
        raise ValueError("invalid speculative decoding mode")
    if draft and normalized["spec_type"] != "draft-simple":
        raise ValueError("draft_model_id requires spec_type=draft-simple; specialized models require advanced flags")
    if normalized["spec_type"] == "draft-simple" and not draft:
        raise ValueError("draft-simple requires draft_model_id")
    if config.get("require_model_api_keys", True) and not normalized["api_key_file"]:
        raise ValueError("API key file required for public HTTPS model endpoints")
    if normalized["api_key_file"] is not None and not Path(normalized["api_key_file"]).is_file():
        raise ValueError("API key file not found")
    extra = normalized["extra_args"]
    if not isinstance(extra, list) or len(extra) > 80 or any(not isinstance(v, str) or len(v) > 1024 for v in extra):
        raise ValueError("extra_args must be short list of strings")
    for v in extra:
        if v.split("=", 1)[0] in CONTROLLED_FLAGS or any(v.startswith(x+"=") for x in CONTROLLED_FLAGS):
            raise ValueError(f"reserved flag in extra_args: {v}")
    return model_id, profile_name, normalized

def build_argv(cfg, models, model_id, profile, launch, backend_port):
    argv = [cfg["binary"], "--model", models[model_id]["path"], "--host", "127.0.0.1", "--port", str(backend_port),
            "--alias", model_id, "--ctx-size", str(launch["ctx_size"]), "--n-gpu-layers", str(launch["gpu_layers"]),
            "--threads", str(launch["threads"]), "--threads-batch", str(launch["threads_batch"]),
            "--batch-size", str(launch["batch_size"]), "--ubatch-size", str(launch["ubatch_size"]),
            "--parallel", str(launch["parallel"]), "--flash-attn", launch["flash_attn"],
            "--cache-type-k", launch["cache_type_k"], "--cache-type-v", launch["cache_type_v"], "--metrics"]
    if not launch["kv_offload"]: argv.append("--no-kv-offload")
    if launch["mlock"]: argv.append("--mlock")
    if launch["no_mmap"]: argv.append("--no-mmap")
    if launch["jinja"]: argv.append("--jinja")
    if launch["api_key_file"]: argv.extend(["--api-key-file", launch["api_key_file"]])
    if launch["spec_type"] != "none":
        argv.extend(["--spec-type", launch["spec_type"]])
    if launch["draft_model_id"]:
        argv.extend(["--spec-draft-model", models[launch["draft_model_id"]]["path"],
                     "--spec-draft-n-max", str(launch["draft_tokens"])])
    argv.extend(launch["extra_args"])
    return argv

class Supervisor:
    def __init__(self, config):
        self.cfg = config
        self.dir = Path(config["state_dir"])
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / "state.json"
        self.state = read_json(self.file, {"models": {}, "instances": {}, "scenes": {}, "history": []})
        self.state.setdefault("models", {})
        self.state.setdefault("instances", {})
        self.state.setdefault("scenes", {})
        self.state.setdefault("history", [])
        self.lock = asyncio.Lock()
        self._last_metrics = {}
        self._interval = max(2, int(config.get("poll_seconds", 4)))
        # Disk is authoritative for process ownership after restart. The
        # Popen object is deliberately not required for reattachment.
        for item in self.state["instances"].values():
            if item.get("status") in ("running", "loading", "starting", "draining", "unhealthy") and not valid_running(item):
                item["status"] = "exited"
                item["healthy"] = False
        self._save()

    def _save(self):
        atomic_json(self.file, self.state)

    def _manifest(self):
        routes = [{"public_port": x["public_port"], "backend_port": x["backend_port"]}
                  for x in self.state["instances"].values()
                  if x.get("status") in ("starting", "loading", "running", "unhealthy")]
        return {"routes": sorted(routes, key=lambda r: r["public_port"])}

    def _apply_proxy(self):
        path = self.dir / "proxy.json"
        old = path.read_bytes() if path.exists() else None
        manifest = self._manifest()
        atomic_json(path, manifest, mode=0o640)
        command = self.cfg.get("nginx_apply_command", [])
        if not command:
            return
        try:
            run = subprocess.run(command, capture_output=True, text=True, timeout=30)
            if run.returncode:
                raise RuntimeError((run.stderr or run.stdout).strip()[:2500])
        except Exception:
            # Restore desired manifest on error; helper itself restores nginx config.
            if old is None:
                path.unlink(missing_ok=True)
            else:
                from .common import atomic_bytes
                atomic_bytes(path, old)
            raise

    def snapshot(self):
        result = copy.deepcopy(self.state)
        result["system"] = {"memory": memory(), "gpus": gpus(), "profiles": self.cfg["profiles"],
                            "public_ports": self.cfg["public_ports"], "backend_ports": self.cfg["backend_ports"],
                            "admin_port": self.cfg["admin_port"]}
        for inst in result["instances"].values():
            inst["alive"] = valid_running(inst)
        return result

    def scan(self):
        count = 0
        for dirname in self.cfg.get("model_dirs", []):
            root = Path(dirname)
            if not root.is_dir(): continue
            for path in root.rglob("*.gguf"):
                if re.search(r"-\d{5}-of-\d{5}\.gguf$", path.name) and not re.search(r"-00001-of-\d{5}\.gguf$", path.name):
                    continue
                full = str(path.resolve())
                if any(m["path"] == full for m in self.state["models"].values()):
                    continue
                stem = re.sub(r"-00001-of-\d{5}$", "", path.stem)
                base = re.sub("[^a-zA-Z0-9_.-]", "-", stem)[:56].strip("-.") or "model"
                if not base[0].isalnum(): base = "m" + base
                mid = base
                n = 2
                while mid in self.state["models"]:
                    mid, n = f"{base[:50]}-{n}", n + 1
                self.state["models"][mid] = {"path": full, "hf_repo": "", "card": {"notes": "", "parameters": "", "license": "", "url": ""}, "launch": {}}
                count += 1
        self._save()
        return count

    def add_model(self, value):
        mid = name(value["id"])
        path = str(Path(value["path"]).resolve())
        if not Path(path).is_file() or not path.lower().endswith(".gguf"):
            raise ValueError("model must be an existing GGUF file")
        card = value.get("card", {})
        if not isinstance(card, dict): raise ValueError("card must be an object")
        entry = {"path": path, "hf_repo": str(value.get("hf_repo", "")), "card": card,
                 "launch": value.get("launch", {})}
        if not isinstance(entry["launch"], dict): raise ValueError("launch must be an object")
        self.state["models"][mid] = entry
        self._save()
        return entry

    def model_info(self, mid):
        m = self.state["models"][name(mid)]
        path = Path(m["path"])
        data = {"id": mid, **m, "exists": path.is_file()}
        if path.is_file():
            data["size_bytes"] = disk_size(path)
            try: data["gguf"] = metadata(path)
            except (OSError, ValueError, EOFError): data["gguf"] = {}
        return data

    def fit(self, profile, ctx=8192, ck="f16", cv="f16"):
        prof = self.cfg["profiles"].get(profile)
        if prof is None: raise ValueError("unknown profile")
        gpu_pool = [g for g in gpus() if g["index"] in prof["gpu_ids"]]
        gpu_free = sum(max(0, g["total"]-g["used"]) for g in gpu_pool)
        ram_free = memory()["available"]
        results = []
        for mid in self.state["models"]:
            try:
                info = self.model_info(mid)
                if not info["exists"]: continue
                kv = estimate_kv(info.get("gguf", {}), ctx, ck, cv)
                # Overhead multiplier is explicitly a heuristic, not model-specific.
                total = int(info["size_bytes"] * 1.15 + (kv or 0) + 0.5*GIB)
                available = (gpu_free - self.cfg.get("min_vram_headroom_gib", 1.5)*GIB) if prof["gpu_ids"] else ram_free
                results.append({"id": mid, "disk_bytes": info["size_bytes"], "kv_estimate_bytes": kv,
                                "rough_required_bytes": total, "available_bytes": int(max(0, available)),
                                "likely_fits": total <= available, "confidence": "low", "note": "Assumes full model on chosen device(s), f16 or selected KV cache, +15% model / 0.5 GiB overhead. Does not handle MoE activation, GPU split, MMProj, runtime buffers or fragmented memory."})
            except (OSError, ValueError): continue
        return sorted(results, key=lambda x: (not x["likely_fits"], x["rough_required_bytes"]))

    def _allocate(self, spec):
        existing = list(self.state["instances"].values())
        public_used = {i["public_port"] for i in existing if i["status"] not in ("exited", "failed", "stopped")}
        backend_used = {i["backend_port"] for i in existing if i["status"] not in ("exited", "failed", "stopped")}
        allowed_public = allowed_ports(self.cfg["public_ports"])
        p = spec.get("public_port")
        if p is not None:
            port(p)
            if p not in allowed_public: raise ValueError("public port outside allowed ranges/sets")
            if p in public_used: raise ValueError("public port already assigned")
            if not can_bind(p, "0.0.0.0"): raise ValueError("public port in use by another process")
        else:
            p = next((x for x in allowed_public if x not in public_used and can_bind(x, "0.0.0.0")), None)
        if p is None: raise ValueError("no available public ports")
        b = next((x for x in allowed_ports(self.cfg["backend_ports"]) if x not in backend_used and can_bind(x)), None)
        if b is None: raise ValueError("no available backend ports")
        return p, b

    async def start(self, spec):
        async with self.lock:
            iid = name(spec["name"])
            if iid in self.state["instances"] and self.state["instances"][iid]["status"] not in ("exited", "failed", "stopped"):
                raise ValueError("instance name already active")
            mid, profile, launch = config_for_instance(self.cfg, self.state["models"], spec)
            pp, bp = self._allocate(spec)
            argv = build_argv(self.cfg, self.state["models"], mid, profile, launch, bp)
            logpath = self.dir / "logs" / (iid + ".log")
            logpath.parent.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ)
            env.update(self.cfg["profiles"][profile]["env"])
            try:
                with open(logpath, "ab", buffering=0) as log:
                    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                            cwd=str(self.dir), start_new_session=True, env=env, close_fds=True)
                item = {"name": iid, "model_id": mid, "profile": profile, "launch": launch,
                        "public_port": pp, "backend_port": bp, "pid": proc.pid,
                        "created_at": psutil.Process(proc.pid).create_time(), "started": now(),
                        "status": "starting", "healthy": False, "argv": argv, "log": str(logpath)}
                self.state["instances"][iid] = item
                self._save()
                try: self._apply_proxy()
                except Exception:
                    os.killpg(proc.pid, signal.SIGTERM)
                    item["status"] = "failed"
                    self._save()
                    raise
                return copy.deepcopy(item)
            except OSError as e:
                raise ValueError(f"failed to launch: {e}") from e

    async def stop(self, iid, force=False):
        async with self.lock:
            item = self.state["instances"].get(name(iid))
            if not item: raise ValueError("unknown instance")
            if item["status"] in ("stopped", "exited", "failed"): return item
            if force:
                if valid_running(item): os.killpg(item["pid"], signal.SIGKILL)
                item["status"] = "stopped"
            else:
                old = item["status"]
                item["status"] = "draining"
                try: self._apply_proxy()
                except Exception:
                    item["status"] = old
                    raise
                item["draining_since"] = now()
                item["drain_idle_polls"] = 0
            item["healthy"] = False
            self._save()
            if force: self._apply_proxy()
            return copy.deepcopy(item)

    def save_scene(self, scene):
        sid = name(scene["name"])
        instances = scene.get("instances")
        if not isinstance(instances, list) or not instances or len(instances) > 100:
            raise ValueError("scene needs 1-100 instances")
        for inst in instances:
            name(inst["name"])
            config_for_instance(self.cfg, self.state["models"], inst)
        self.state["scenes"][sid] = instances
        self._save()
        return sid

    async def apply_scene(self, sid):
        scene = copy.deepcopy(self.state["scenes"].get(name(sid)))
        if scene is None: raise ValueError("unknown scene")
        launched = []
        try:
            for spec in scene:
                launched.append((await self.start(spec))["name"])
        except Exception:
            # Roll back *only* processes created by this application attempt.
            for iid in launched:
                await self.stop(iid, force=True)
            raise
        return launched

    def save_running_scene(self, sid):
        scene = []
        for item in self.state["instances"].values():
            if item["status"] in ("starting", "loading", "running", "unhealthy"):
                scene.append({"name": item["name"], "model_id": item["model_id"], "profile": item["profile"],
                              "public_port": item["public_port"], "launch": item["launch"]})
        return self.save_scene({"name": sid, "instances": scene})

    def _active_connections(self, item):
        try:
            process = psutil.Process(item["pid"])
            return sum(1 for c in process.net_connections(kind="tcp") if c.status == psutil.CONN_ESTABLISHED
                       and c.laddr and c.laddr.port == item["backend_port"])
        except (psutil.Error, OSError):
            return None

    async def poll(self):
        async with self.lock:
            changed = False
            for item in self.state["instances"].values():
                status = item.get("status")
                if status in ("stopped", "exited", "failed"): continue
                if not valid_running(item):
                    item["status"] = "exited"
                    item["healthy"] = False
                    changed = True
                    continue
                if status == "draining":
                    active = self._active_connections(item)
                    item["active_backend_connections"] = active
                    # Never silently terminate while a connection might be active
                    # or when process inspection is unavailable.
                    if active == 0:
                        item["drain_idle_polls"] = item.get("drain_idle_polls", 0) + 1
                    else:
                        item["drain_idle_polls"] = 0
                    if item["drain_idle_polls"] >= 3:
                        try: os.killpg(item["pid"], signal.SIGTERM)
                        except ProcessLookupError: pass
                        item["status"] = "stopped"
                    changed = True
                    continue
                try:
                    timeout = aiohttp.ClientTimeout(total=2)
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.get(f"http://127.0.0.1:{item['backend_port']}/health") as resp:
                            healthy = resp.status == 200
                        item["healthy"] = healthy
                        item["status"] = "running" if healthy else "loading"
                        if healthy:
                            try:
                                async with session.get(f"http://127.0.0.1:{item['backend_port']}/metrics") as r:
                                    if r.status == 200:
                                        metrics = await r.text()
                                        counters = {}
                                        for line in metrics.splitlines():
                                            if line.startswith("#") or not line.strip(): continue
                                            fields = line.split()
                                            if len(fields) >= 2 and ("tokens" in fields[0] or "seconds" in fields[0]):
                                                try: counters[fields[0]] = float(fields[1])
                                                except ValueError: pass
                                        item["metrics"] = counters
                                        preferred = [k for k in counters if k.endswith(("tokens_predicted_total", "predicted_tokens_total", "tokens_generated_total"))]
                                        if preferred:
                                            key = sorted(preferred)[0]
                                            previous = self._last_metrics.get(item["name"])
                                            stamp = time.monotonic()
                                            if previous and counters[key] >= previous[1]:
                                                elapsed = stamp-previous[0]
                                                if elapsed > 0: item["tokens_per_sec"] = round((counters[key]-previous[1])/elapsed, 2)
                                            self._last_metrics[item["name"]] = (stamp, counters[key])
                            except (aiohttp.ClientError, asyncio.TimeoutError): pass
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    item["healthy"] = False
                    item["status"] = "unhealthy"
                changed = True
            if changed:
                try: self._apply_proxy_if_changed()
                except Exception as e: self.state["last_proxy_error"] = str(e)
                self._save()

    def _apply_proxy_if_changed(self):
        path = self.dir / "proxy.json"
        desired = self._manifest()
        if read_json(path) != desired:
            self._apply_proxy()

    async def run_poll(self):
        while True:
            try: await self.poll()
            except Exception as exc:
                self.state["last_poll_error"] = str(exc)
                self._save()
            await asyncio.sleep(self._interval)
