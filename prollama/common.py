"""Configuration, validation, and atomic JSON storage."""
import json
import os
import re
import socket
import tempfile
from pathlib import Path

NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")

def name(value):
    if not isinstance(value, str) or not NAME_RE.fullmatch(value):
        raise ValueError("names must be 1-64 ASCII letters, numbers, '.', '_' or '-' (start with alphanumeric)")
    return value

def port(value):
    if isinstance(value, str):
        value = int(value)
    if type(value) is not int or not (1024 <= value <= 65535):
        raise ValueError("port must be an integer between 1024 and 65535")
    return value

def allowed_ports(spec):
    ports = set()
    for lo, hi in spec.get("ranges", []):
        lo, hi = int(lo), int(hi)
        if hi < lo or hi - lo > 10000:
            raise ValueError("invalid port range")
        ports.update(range(lo, hi + 1))
    for p in spec.get("sets", []):
        ports.add(port(p))
    return sorted(ports)

def can_bind(p, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, p))
            return True
        except OSError:
            return False

def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default

def atomic_json(path, value, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as file:
            json.dump(value, file, indent=2, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def config_load(path):
    cfg = read_json(path)
    if not isinstance(cfg, dict):
        raise ValueError("configuration must be a JSON object")
    if not Path(cfg["binary"]).is_file():
        raise ValueError(f"llama-server executable not found: {cfg['binary']}")
    if not os.access(cfg["binary"], os.X_OK):
        raise ValueError("llama-server is not executable")
    public = set(allowed_ports(cfg["public_ports"]))
    backend = set(allowed_ports(cfg["backend_ports"]))
    if not public or not backend or public & backend:
        raise ValueError("public/backend port pools must be nonempty and disjoint")
    if cfg.get("admin_host", "127.0.0.1") != "127.0.0.1":
        raise ValueError("management backend must bind to 127.0.0.1; TLS is terminated by nginx")
    if cfg["admin_port"] in public | backend:
        raise ValueError("management backend port overlaps port pools")
    for pn, profile in cfg["profiles"].items():
        name(pn)
        if not isinstance(profile.get("env"), dict) or not isinstance(profile.get("gpu_ids"), list):
            raise ValueError("profile requires env object and gpu_ids array")
        for k, v in profile["env"].items():
            if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", k) or not isinstance(v, str):
                raise ValueError("invalid profile environment variable")
    return cfg

def atomic_bytes(path, value, mode=0o640):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
