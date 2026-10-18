"""Hardware inventory. Edit named GPU profiles in config.json, not in the launcher.

For multi-GPU ROCm: HIP_VISIBLE_DEVICES=0,1 (or explicit PCI IDs as supported
by the local HIP runtime). For NVIDIA: CUDA_VISIBLE_DEVICES=0,1.
The HIP index to PCI bus ID assignment should be verified with rocm-smi.
"""
import os
import re
import subprocess
from pathlib import Path
import psutil

GIB = 1024 ** 3

def memory():
    v = psutil.virtual_memory()
    return {"total": v.total, "available": v.available, "used": v.used, "percent": v.percent,
            "cpu_percent": psutil.cpu_percent(interval=None)}

def gpus():
    items = []
    drm = Path("/sys/class/drm")    
    for card in sorted((p for p in drm.glob("card*") if re.fullmatch(r"card\d+", p.name)),
        key=lambda p: int(p.name[4:])
    ):
        d = card / "device"
        total = d / "mem_info_vram_total"
        used = d / "mem_info_vram_used"
        if not total.exists():
            continue
        try:
            pci = os.path.basename(os.path.realpath(d))
            busy_file = d / "gpu_busy_percent"
            items.append({"index": len(items), "vendor": "AMD", "name": f"AMD GPU ({pci})",
                          "pci": pci, "total": int(total.read_text()), "used": int(used.read_text()),
                          "utilization": int(busy_file.read_text()) if busy_file.exists() else None})
        except (OSError, ValueError):
            continue
    try:
        run = subprocess.run(["nvidia-smi", "--query-gpu=index,name,pci.bus_id,memory.total,memory.used,utilization.gpu",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=2)
        if run.returncode == 0:
            for line in run.stdout.splitlines():
                parts = [s.strip() for s in line.split(",")]
                if len(parts) == 6:
                    idx, gpu_name, pci, total, used, busy = parts
                    items.append({"index": int(idx), "vendor": "NVIDIA", "name": gpu_name, "pci": pci,
                                  "total": int(total) * 1024 * 1024, "used": int(used) * 1024 * 1024,
                                  "utilization": int(busy)})
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return items
