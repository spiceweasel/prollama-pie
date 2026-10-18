"""Read enough GGUF metadata for transparent, approximate KV estimates.

This does not read tensors or download files. Unsupported GGUF types yield
partial metadata; no false guarantee of memory fit is made.
"""
import re
import struct
from pathlib import Path
from .hardware import GIB

FMT = {0:"B",1:"b",2:"H",3:"h",4:"I",5:"i",6:"f",7:"?",10:"Q",11:"q",12:"d"}
KV_BYTES = {"f32":4, "f16":2, "bf16":2, "q8_0":34/32, "q4_0":18/32,
            "q4_1":20/32, "q5_0":22/32, "q5_1":24/32, "iq4_nl":0.6}

def metadata(path):
    result = {}
    with open(path, "rb") as file:
        if file.read(4) != b"GGUF":
            raise ValueError("Not a GGUF file")
        version = struct.unpack("<I", file.read(4))[0]
        if version not in (2, 3):
            raise ValueError("unsupported GGUF version")
        _tensor_count, fields = struct.unpack("<QQ", file.read(16))
        if fields > 100000:
            raise ValueError("implausible GGUF metadata")
        def nbytes(n):
            if n > 32 * 1024 * 1024:
                raise ValueError("oversized GGUF metadata field")
            b = file.read(n)
            if len(b) != n:
                raise ValueError("truncated GGUF")
            return b
        def val(kind):
            if kind == 8:
                return nbytes(struct.unpack("<Q", nbytes(8))[0]).decode("utf-8", "replace")
            if kind == 9:
                inner, length = struct.unpack("<IQ", nbytes(12))
                if length > 1000000:
                    raise ValueError("oversized GGUF array")
                return [val(inner) for _ in range(length)]
            if kind not in FMT:
                raise ValueError(f"unsupported GGUF metadata type {kind}")
            fmt = FMT[kind]
            return struct.unpack("<" + fmt, nbytes(struct.calcsize(fmt)))[0]
        for _ in range(fields):
            key = nbytes(struct.unpack("<Q", nbytes(8))[0]).decode("utf-8", "replace")
            kind = struct.unpack("<I", nbytes(4))[0]
            value = val(kind)
            if key == "general.architecture" or key.endswith(("block_count", "embedding_length", "head_count", "head_count_kv", "key_length", "value_length", "context_length")):
                result[key] = value
    return result

def estimate_kv(meta, ctx, dtype_k="f16", dtype_v="f16"):
    arch = meta.get("general.architecture")
    if not arch:
        return None
    prefix = str(arch) + "."
    def field(k): return meta.get(prefix + k)
    layers = field("block_count")
    embd = field("embedding_length")
    heads = field("attention.head_count")
    kv_heads = field("attention.head_count_kv") or heads
    if not (all(isinstance(v, int) and v > 0 for v in (layers, embd, heads, kv_heads))):
        return None
    kd = field("attention.key_length") or (embd // heads)
    vd = field("attention.value_length") or (embd // heads)
    if dtype_k not in KV_BYTES or dtype_v not in KV_BYTES:
        return None
    return int(ctx * layers * kv_heads * (kd * KV_BYTES[dtype_k] + vd * KV_BYTES[dtype_v]))

def disk_size(path):
    p = Path(path)
    match = re.match(r"^(.*)-\d{5}-of-(\d{5})\.gguf$", p.name, re.I)
    if not match:
        return p.stat().st_size
    siblings = list(p.parent.glob(match.group(1) + "-*-of-" + match.group(2) + ".gguf"))
    return sum(s.stat().st_size for s in siblings)
