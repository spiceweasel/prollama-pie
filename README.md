# 🥧 proLLaMa-Pie

### Serving up slices of local LLMs. BAM!

**One host. Many llama.cpp servers. One nginx TLS gateway. No Docker. No database service.**

Welcome to **proLLaMa-Pie!**

One machine. Multiple models. A whole lot of slices.

proLLaMa-Pie is a lightweight, container-free orchestration platform for [llama.cpp](https://github.com/ggml-org/llama.cpp). Fire up multiple inference servers, allocate GPUs, monitor hardware resources, and serve every model securely through a single nginx reverse proxy.

Built around **your own `llama-server` executable**, proLLaMa-Pie inventories local GGUF models, launches and monitors independent server instances, and manages their configurations. Each instance runs on its own dynamically allocated backend port and is exposed through an individually assigned **HTTPS port**, all secured by **one nginx TLS certificate**.

A responsive web dashboard and Docker Compose-style CLI provide two convenient ways to manage your models, with support for CPU, AMD ROCm, and NVIDIA CUDA environments. Save your favorite configurations, optimize hardware utilization, and serve up as many slices as your system can handle.

**Pick your models. Season your configurations. Serve up a slice.**

**BAM! Let's kick local inference up a notch.**

> **Release status: 0.1.0 initial implementation / public alpha.** The project has automated unit/smoke tests, but has **not** yet been validated against a production ROCm or CUDA system, sustained inference traffic, all llama.cpp builds, or every Linux distribution. Read the [limitations](#limitations-and-operational-guarantees) before exposing it beyond a trusted LAN.

## What it does

- **Manage many independent llama-server processes** on one Linux host; launch the same GGUF repeatedly with different settings and ports.
- **One certificate, many HTTPS listeners**: e.g. `https://llama.home.arpa:8080/v1/chat/completions`, `:8081`, `:8082`, plus `:8443` for the dashboard.
- **Separate public and backend ports**: nginx listens on ports drawn from approved ranges/sets; each backend uses an independently allocated free local port (loopback only).
- **Safe configuration updates**: an argument-free, root-owned nginx apply helper generates a restricted `http`-context include, checks port conflicts, runs `nginx -t`, and **gracefully reloads**. It never uses `systemctl restart nginx` for routine port changes; it restores the former file if validation/reload fails.
- **Persistent state**: atomic local JSON stores instances, PID/create-time identity, launch settings, scenes, and model metadata; child processes intentionally survive a supervisor restart.
- **Stop without cutting active streams**: ordinary `down` removes the nginx mapping, gracefully reloads nginx, and waits for all observable established connections to the backend to disappear before stopping it. `down --force` can terminate active requests.
- **Profiles**: quick-select CPU, GPU 0, GPU 1, or GPU 0+1. Profile environment variables include `HIP_VISIBLE_DEVICES` and/or `CUDA_VISIBLE_DEVICES`.
- **Resource dashboard**: available system RAM, CPU load, AMD sysfs VRAM/use/utilization and NVIDIA `nvidia-smi` telemetry, instance health and configuration, and low-confidence model/KV memory estimates.
- **Model catalog**: recursive `.gguf` scans, including primary shards; size on disk; selected GGUF metadata; saved Hugging Face repository/card fields; model-specific default launch settings.
- **Scenes**: save the currently running set of model instances; import named scenes as JSON; relaunch a scene with its saved options/ports.
- **llama.cpp tuning**: context, GPU offload layers, threads and prompt threads, logical/physical batches, parallel slots, flash attention, KV types and placement, mmap/mlock, and n-gram or draft-model speculative decoding.
- **CLI and web UI share one supervisor**: no independent scripts fighting over port assignments. No runtime database, Node build step, system-wide Python dependencies, or Docker.

## Architecture

```text
                         local clients (TLS, same hostname/certificate)
             https://llama.home.arpa:8443       :8080      :8081     :8082
                         |                         |          |         |
                         +-------------------------+----------+---------+
                                                    |
                                          nginx (one master)
                                          TLS 1.2 / TLS 1.3
                                                    |
                           :8443 -> 127.0.0.1:18765 (admin web & API)
                           :8080 -> 127.0.0.1:18080 (llama-server A)
                           :8081 -> 127.0.0.1:18081 (llama-server B)
                           :8082 -> 127.0.0.1:18082 (llama-server C)
                                                     ^
                             prollama-pie daemon (prollama user)
                               |                       |
                  control.sock (CLI)          atomic JSON state
                               |                       |
                   port allocation, health polling, model discovery,
                   process reattachment, GPU metrics, scenes and drain
                               |
                       restricted nginx helper (sudo)
                        nginx -t && systemctl reload nginx
```

**Trust boundary:** The daemon is nonroot; privileged nginx file writes and reloads happen only through the no-argument helper, which builds server blocks from validated integer port mappings. `proxy-settings.json` is root-owned and pins the cert paths, output path and backend admin port. Web administration requires Basic authentication **inside the Python application**, even for connections from localhost. The CLI uses a Unix socket protected by filesystem permissions. Model endpoints use llama.cpp's own API keys, enabled by default through an API-key file.

**Single-host scope:** Multiple machines can each run their own installation, but no shared fleet controller, discovery across machines, or coordinated GPU scheduling is implemented in 0.1.0.

## Prerequisites

- Linux host (Ubuntu 22.04+/Fedora current releases are the intended targets); Python **3.10+**, Python venv and pip, `nginx` with HTTP SSL module, `openssl`, `sudo`, `systemd`, and `visudo`.
- A locally built or installed `llama-server` **executable**. You build and update llama.cpp yourself. This project does not build models, compile ROCm, or download model weights.
- Local GGUF files accessible to the `prollama` service account. Check filesystem permissions for the parent directories as well as model files.
- For AMD GPUs: suitable ROCm/HIP permissions and working device nodes (`/dev/kfd`, `/dev/dri/renderD*`); for NVIDIA: accessible NVIDIA drivers and `nvidia-smi` for telemetry. Environment profiles must match the GPU backend in the supplied binary.
- One DNS hostname (`llama.home.arpa` in the examples), resolving to your host's LAN IP, and a chosen range of firewall-allowed public ports. Port **8443** is reserved for admin in the supplied configuration.

### Quick installation — Ubuntu/Debian

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx openssl sudo
# Install the repo from this directory:
sudo ./deploy/install.sh
# Adjust paths for YOUR llama-server build and GGUF directories:
sudoedit /etc/prollama-pie/config.json
```

On Fedora, use `sudo dnf install python3 python3-pip nginx openssl sudo`, verify `python3 -m venv` works, and run the same install script. The installer does **not** overwrite existing configuration/password files; it installs the root-owned executable/helper, systemd unit, and creates a dedicated service account. Re-run after upgrading repo code, then `sudo systemctl restart prollama-pie` if you deliberately want to restart the *supervisor* (running llama-server children stay alive).

**Change** these example fields before starting:

```json
{
  "binary": "/opt/llama.cpp/build-rocm/bin/llama-server",
  "model_dirs": ["/srv/models", "/mnt/models"],
  "public_ports": {"ranges": [[8080, 8120]], "sets": [8200, 8201]},
  "backend_ports": {"ranges": [[18080, 18200]], "sets": []}
}
```

Do not replace the entire JSON file with the small fragment above; edit the corresponding keys in `config/config.example.json` installed under `/etc/prollama-pie/config.json`. GPU profile examples include CPU, ROCm GPU 0, CUDA GPU 1, and both; edit them to match your hardware.

### TLS: generate your own local CA and leaf certificate

> For a public DNS domain you control, prefer certificates from a publicly trusted CA such as Let's Encrypt and use your existing renewal mechanism. The following is intended for an **internal/private DNS name**. Never distribute your CA **private key**.

```bash
# From the cloned repo. The IP is optional but lets clients connect by IP
# without triggering a certificate name mismatch.
./cert/generate_cert.sh llama.home.arpa 192.168.1.50 /tmp/prollama-pki

sudo install -d -m 0700 /etc/nginx/ssl
sudo install -o root -g root -m 0644 /tmp/prollama-pki/prollama-pie.crt /etc/nginx/ssl/
sudo install -o root -g root -m 0600 /tmp/prollama-pki/prollama-pie.key /etc/nginx/ssl/
# Keep CA public cert available for enrolling clients; isolate CA private key
sudo install -d -m 0700 /etc/prollama-pie/pki
sudo install -m 0644 /tmp/prollama-pki/prollama-ca.crt /etc/prollama-pie/pki/
# Move /tmp/prollama-pki/prollama-ca.key to OFFLINE secure storage.

# In root-owned /etc/prollama-pie/proxy-settings.json, match the hostname,
# certificate paths, frontend admin port and backend admin port.
sudoedit /etc/prollama-pie/proxy-settings.json
sudo systemctl enable --now nginx
sudo /usr/local/sbin/prollama-nginx-apply  # checks nginx -t; graceful reload
sudo systemctl enable --now prollama-pie
sudo systemctl status prollama-pie --no-pager
```

In `proxy-settings.json`, `listen_address` controls whether nginx listens only on `127.0.0.1` or on `0.0.0.0` for LAN access. `server_name` must match your certificate's DNS SAN. A **single** certificate is shared by all model HTTPS ports and the admin UI; certificates identify **hostnames/IPs, not ports**.

**Firewall**: expose only public HTTPS ports you intend to use and admin 8443; do **not** expose the 18080+ backend pool or port 18765. Backends and admin are always bound to loopback. Restrict LAN access to trusted client networks; don't expose this alpha to the public Internet without additional hardening and a reviewed authentication policy.

```bash
# Example, assuming Ubuntu ufw and a trusted subnet; adapt as needed:
sudo ufw allow from 192.168.1.0/24 to any port 8443 proto tcp
sudo ufw allow from 192.168.1.0/24 to any port 8080:8120 proto tcp
```

### Client CA trust (do NOT copy private keys)

Copy **`prollama-ca.crt`**, not the leaf cert, to each trusted client:

```bash
# On the server, place the PUBLIC CA cert somewhere your SSH account can read:
sudo install -m 0644 /etc/prollama-pie/pki/prollama-ca.crt /tmp/prollama-ca.crt
# On the client:
scp user@server_machine:/tmp/prollama-ca.crt ./prollama-ca.crt
# You can remove the temporary public certificate afterward.
```

| Client | Steps |
|---|---|
| Ubuntu/Debian | `sudo cp prollama-ca.crt /usr/local/share/ca-certificates/prollama-ca.crt && sudo update-ca-certificates` |
| Fedora/RHEL | `sudo cp prollama-ca.crt /etc/pki/ca-trust/source/anchors/ && sudo update-ca-trust extract` |
| Windows (Administrator) | `certutil -addstore -f Root prollama-ca.crt` (adds a trusted root; do this only on machines you control) |
| Firefox | Settings → Privacy & Security → Certificates → View Certificates → Authorities → Import CA; enable trust for websites. Alternatively configure `security.enterprise_roots.enabled` appropriately. |
| Java/JVM | Prefer a dedicated truststore: `keytool -importcert -alias prollama -file prollama-ca.crt -keystore ./prollama-truststore.p12 -storetype PKCS12`; start Java with `-Djavax.net.ssl.trustStore=/path/prollama-truststore.p12`. |

Configure internal DNS or `/etc/hosts` so `llama.home.arpa` resolves to your actual server. For browser error diagnosis: verify that the hostname/IP in your URL is a **subjectAltName** in the server certificate. The supplied certificate script creates a long-lived private CA and a 397-day leaf certificate; renew the leaf before it expires and gracefully reload nginx.

### Credentials

```bash
# Dashboard uses HTTP Basic, inside HTTPS (never use direct HTTP remotely)
sudo cat /etc/prollama-pie/admin-password
# Username: admin (editable in config.json)

# Default model endpoint API key (each line is one accepted key for llama.cpp)
sudo cat /etc/prollama-pie/model-keys

# Example test, replace with actual hostname/key:
curl --cacert ./prollama-ca.crt \
  -H 'Authorization: Bearer YOUR_MODEL_API_KEY' \
  https://llama.home.arpa:8080/v1/models
```

The default key file is passed to **every new** llama-server as `--api-key-file`; each model launch may override the path with a different key file. Root-owned secret files are group-readable by `prollama` only. Manage and rotate them as secrets; changing an API-key file may require relaunching instances depending on your llama.cpp build. TLS does **not** provide API authentication by itself. Some llama.cpp status endpoints (notably `/health`) are intentionally unauthenticated by upstream. Generated **model-facing nginx listeners deny `/health`, `/v1/health`, `/metrics`, `/slots` and `/props`**, while the local supervisor probes the backend directly. Do not mistake upstream keys for universal path authorization of every possible URL.

## CLI: run, list, stop

To access the local Unix socket without `sudo`, add a trusted admin account to the `prollama` group, then log out/in. Group members have **full instance-management access**. Or run the CLI as the service account:

```bash
sudo -u prollama /opt/prollama-pie/venv/bin/prollama models
sudo -u prollama /opt/prollama-pie/venv/bin/prollama scan
sudo -u prollama /opt/prollama-pie/venv/bin/prollama profiles
sudo -u prollama /opt/prollama-pie/venv/bin/prollama doctor
sudo -u prollama /opt/prollama-pie/venv/bin/prollama up qwen-main qwen-32b \
  --profile rocm-0 --port 8080 --ctx-size 32768 --gpu-layers 99 \
  --threads 8 --threads-batch 12 --parallel 2 --flash-attn auto
sudo -u prollama /opt/prollama-pie/venv/bin/prollama ps
sudo -u prollama /opt/prollama-pie/venv/bin/prollama logs qwen-main
sudo -u prollama /opt/prollama-pie/venv/bin/prollama down qwen-main
# In a genuine emergency only:
sudo -u prollama /opt/prollama-pie/venv/bin/prollama down qwen-main --force
```

The `up` command creates a fresh named instance; it does not restart an existing one implicitly. Normal `down` switches the instance to `draining`: nginx stops accepting new traffic on its public port, but existing nginx workers and the backend process remain until established backend connections are gone. There is intentionally **no fixed force-kill timeout** while a connection may be active. Force stop is explicitly disruptive. `prollama ps` shows `draining` state until shutdown.

Useful commands:

```text
prollama ps                   # name, model, GPU profile, both ports, PID, status
prollama status               # detailed instance + hardware state
prollama models               # model catalog and local paths
prollama model-add ID PATH [--hf-repo ORG/REPO] [--card ./card.json]
prollama model-info ID        # size on disk, GGUF header, HF card, defaults
prollama model-import ./my-model.json  # JSON catalog entry + default launch
prollama scan                 # discover new *.gguf in model_dirs
prollama profiles             # named CPU/HIP/CUDA environments
prollama fit --profile rocm-both --ctx 32768
prollama up NAME MODEL_ID [--profile rocm-0] [--port 8080] [...]
prollama down NAME [--force]
prollama logs NAME            # most recent 24 KB
prollama scenes               # saved scene definitions
prollama scene save-running NAME
prollama scene import ./my-scene.json
prollama scene up NAME        # launch a saved group of instances
prollama doctor               # hardware and last proxy error
prollama --json ps            # machine-readable JSON
```

### Reusable scenes

Save the current running set (name, model ID, hardware profile, exact public port, launch options):

```bash
prollama scene save-running research-day
prollama down small-cpu
prollama scene up research-day
```

Or import a scene (same schema used by the web UI):

```json
{
  "name": "two-rocms",
  "instances": [
    {"name":"qwen-a", "model_id":"qwen-32b", "profile":"rocm-0", "public_port":8080, "launch":{"ctx_size":16384, "gpu_layers":99, "parallel":2}},
    {"name":"qwen-b", "model_id":"qwen-14b", "profile":"rocm-1", "public_port":8081, "launch":{"ctx_size":32768, "gpu_layers":99}}
  ]
}
```

Import and apply with `prollama scene import ./two-rocms.json` then `prollama scene up two-rocms`. If a scene fails partway through launch, the supervisor force-stops instances it started in this batch; preexisting instances are left alone. A scene is a **launch set**, not a continuously reconciled deployment: manually stopping one member does not restart it.

### GPU environments and multi-GPU

Edit `/etc/prollama-pie/config.json` to create arbitrarily many named profiles:

```json
"profiles": {
  "cpu": {"description":"CPU only", "env":{"HIP_VISIBLE_DEVICES":"", "CUDA_VISIBLE_DEVICES":""}, "gpu_ids":[]},
  "rocm-0": {"description":"ROCm 0", "env":{"HIP_VISIBLE_DEVICES":"0"}, "gpu_ids":[0]},
  "rocm-1": {"description":"ROCm 1", "env":{"HIP_VISIBLE_DEVICES":"1"}, "gpu_ids":[1]},
  "rocm-both": {"description":"ROCm 0 + 1", "env":{"HIP_VISIBLE_DEVICES":"0,1"}, "gpu_ids":[0,1]},
  "nvidia-both": {"description":"CUDA GPU 0 + 1", "env":{"CUDA_VISIBLE_DEVICES":"0,1"}, "gpu_ids":[0,1]}
}
```

`gpu_ids` are **telemetry labels**, while the environment variables actually determine which GPUs llama.cpp can see. Check `rocminfo`, `rocm-smi`, `nvidia-smi`, and `llama-server --list-devices` because PCI/sysfs enumeration and runtime device order can differ. Selecting two visible GPUs makes them *available* to llama.cpp; to adjust **how** weights are split between them, use supported `--split-mode`, `--tensor-split`, or `--device` options via the model's saved launch `extra_args` field (subject to your build). The CPU profile **requires** `--n-gpu-layers 0`, and also sets `HIP_VISIBLE_DEVICES` empty for CPU-only.

After editing profiles/config, restart the **supervisor** (`sudo systemctl restart prollama-pie`), not nginx and not the existing llama-server children. Old children retain their original environment; newly launched processes use updated profiles.

### Model cards and saved launch defaults

Register a model with card metadata:

```json
{"id":"qwen-32b", "path":"/srv/models/Qwen-32B-Q4_K_M.gguf", "hf_repo":"Qwen/example-repo",
 "card":{"parameters":"32B", "quantization":"Q4_K_M", "license":"Apache-2.0", "notes":"quantization and prompt format notes", "url":"https://huggingface.co/Qwen/example-repo"},
 "launch":{"ctx_size":16384,"gpu_layers":99,"flash_attn":"auto","threads":8,"parallel":2}}
```

`POST /api/models` accepts this object; `prollama model-import ./config/model.example.json` reads a complete model declaration from an editable JSON file. CLI `model-add` supports `--card card.json` (model default launch settings can be saved through the web JSON form or API). Model metadata is *local*, not downloaded or verified against Hugging Face. Never assume metadata matches the exact GGUF without confirming it yourself. Importing a model under the same ID updates its catalog record but does **not** mutate a process already running.

## Web dashboard

Open **`https://llama.home.arpa:8443/`** and authenticate with username `admin` and the contents of `/etc/prollama-pie/admin-password`. It includes:

1. CPU/RAM/VRAM utilization (5-second display refresh).
2. Instance launch/stop, per-process settings, logs, health statuses, assigned ports.
3. Model discovery, explicit GGUF registration, HF card inspection, approximate memory fit.
4. Controls for speculative draft model and size, KV precisions and placement, GPU layers, context, batching, parallel slots, threads and Flash Attention.
5. Scene save/import/relaunch.

All authenticated state-changing web requests additionally require a custom header and enforce a same-origin check; no permissive CORS is configured. Model and scene names are validated before insertion into paths or subprocess arguments. Do not expose admin 8443 outside a restricted LAN or VPN.

## llama.cpp performance tuning: what the controls actually mean

**Important:** llama.cpp changes frequently. This repository defaults to the flag spellings published in the [current llama-server CLI docs](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md), but older or custom builds may reject flags. Use `YOUR_LLAMA_SERVER --help`, `--version`, and the instance log when something fails. The supervisor does **not** attempt to replace your build's feature tests.

| UI control | CLI flag | Guidance and caveats |
|---|---|---|
| Speculative mode | `--spec-type draft-simple`, `--spec-draft-model PATH`, `--spec-draft-n-max N` | A smaller compatible draft model proposes tokens. Accuracy should be preserved when supported, but throughput gains depend on acceptance rate, model pair, and hardware. Draft weights/KV consume extra memory; 2–4× speedup is **not** a guarantee. |
| N-gram speculation | `--spec-type ngram-mod` etc. | Speculates without a second model. Test for your workload. |
| Flash Attention | `--flash-attn auto\|on\|off` | Usually worth testing, especially for long contexts. Availability and speed vary by backend. |
| Parallel slots | `--parallel N` | Increases concurrent requests/throughput where resources permit; **not** parallel speculative decoding. Total configured context is distributed across slots. |
| KV data types | `--cache-type-k`, `--cache-type-v` | Set KV precision (f16, q8_0, q4_0 ...). These flags do **not** relocate cache to RAM. Quantized caches can affect quality; backend support varies. |
| KV placement | `--no-kv-offload` | Prevents offloading KV to GPU; keeps KV in host memory. Usually **slower** than VRAM-backed KV on discrete GPUs, and can add PCIe pressure. Test instead of assuming RAM is faster. |
| Threads / batch threads | `--threads`, `--threads-batch` | CPU generation and CPU-side batch/prompt processing respectively. Setting CPU threads **does not automatically move GPU prefill to CPU**. |
| Batch size | `--batch-size` | Logical batch token maximum; raising it can improve batch processing but increase memory. |
| Physical ubatch | `--ubatch-size` | Microbatch token maximum; changes peak temporary memory and prefill performance. |
| GPU layers | `--n-gpu-layers` | **0 means no layers offloaded**, not “all on GPU.” Larger numbers offload more layers (subject to actual model layer count). |
| Memory mapping | default mmap; `--no-mmap` | Mmap often helps load times and sharing page cache. Disable only for a specific issue. |
| RAM page locking | `--mlock` | Can prevent model pages from swapping; requires enough RAM and compatible service resource limits/permissions. |
| Context | `--ctx-size` | 4k/8k/16k/32k/64k/128k/256k defaults in UI; any valid integer allowed. Model architecture and RoPE scaling constrain meaningful supported context. |
| Metrics | `--metrics` | Exposes Prometheus-compatible metrics on *backend localhost only* (proxied model endpoint may also expose it; secure network accordingly). Dashboard collects the numeric counters it finds; counter names vary by build. |

`--parallel` can improve **throughput** without improving the speed of one isolated request. Speculative decoding may improve generation speed but can be slower when the draft model is expensive or frequently rejected. For multiple GPU placement, the split mode and tensor split can matter as much as layers. **The UI does not claim to benchmark or automatically tune your GPU.**

### KV-cache sizing and model fit

From GGUF metadata, a common dense-attention estimate is:

```text
KV_bytes ≈ context_tokens × n_layers × n_kv_heads ×
           (key_head_dim × bytes_per_K + value_head_dim × bytes_per_V)
```

The catalog supports selected GGUF metadata fields, and file size includes matching GGUF shards where recognized. The **fit** view uses `disk_bytes × 1.15 + estimated_KV + 0.5 GiB` compared with available memory minus 1.5 GiB safety headroom (GPU or host RAM by profile). **Confidence is intentionally low**: model disk size may differ from resident tensors; multilayer partial offload, MoE, cross-device split, attention variants, quantization block accounting, context slot behavior, other apps, draft models and ROCm allocators all change memory use. A missing metadata field produces an unknown KV estimate, not proof that KV is zero. Never let this heuristic block a user’s explicit launch; it only reports an advisory result.

## Reverse proxy behavior

The generated `/etc/nginx/conf.d/prollama-pie.conf` is an **`http {}` include** as on Ubuntu/Fedora default nginx configs. It contains an HTTP-context `map` directive and one `server { listen ... ssl; }` block per active public port, plus the dashboard server. It intentionally contains **no global `worker_processes`/`events`/`http` nesting** and no manually hardcoded upstream IDs.

Nginx settings include TLS 1.2/1.3 only; separate root-owned cert/key; session cache with tickets disabled; 4k SSL buffer; websocket Upgrade support; Host/X-Forwarded headers; no proxy response/request buffering (suitable for SSE streaming); 3600s proxy read/send timeouts; no proxy cache/compression. **Nginx reloads are graceful**, so adding/removing ports preserves existing connections *under normal nginx behavior*. Nginx will fork new workers and retain old workers until current requests finish. **Do not configure a short `worker_shutdown_timeout` globally**, use `nginx -t` before reload, and avoid administrative hard restarts while streams run.

If a new public port is occupied by an unrelated service, prollama refuses it. If backend port pools are exhausted, it reports an error rather than reusing a running instance’s port. Config generation is atomic; failed syntax tests restore the old config and do not invoke reload. Actual reload failures are reported and file state restored; verify nginx error logs if the system is in a degraded state.

**Graceful stop limitations:** A drain waits until there are no *observable* established TCP connections to the backend across three successive polls; it does not instrument llama.cpp's internal request scheduler or provide perfect tracking of idle HTTP keep-alive connections. If connection inspection is blocked, it intentionally keeps draining instead of killing a potentially active stream. An unrelated forced process kill, `systemctl restart nginx`, machine crash, SSL termination at a different proxy, or externally configured nginx worker timeout can still interrupt traffic. Do **not** promise uninterrupted streams under those circumstances.

**You do not need to modify or restart nginx by hand on model launch/stop.** Apply the nginx helper manually only at initial install or after root-controlled TLS/front-end settings change.

## JSON storage and APIs

`/var/lib/prollama-pie/state.json` records models, instances, scenes, launch arguments, PID identities, and process status. `/var/lib/prollama-pie/proxy.json` contains only validated integer port mappings; the root helper uses it to update nginx. All writes use temporary files + fsync + atomic replace. **Only one supervisor per state directory** should run; the daemon takes an exclusive `flock` lock on `.daemon.lock` to prevent concurrent writers, and systemd is the supported instance manager. Back up state, configuration, model metadata, and certs separately; back up private keys securely.

The CLI connects to `/run/prollama-pie/control.sock`; it is group-protected. The web API lives on the dashboard HTTPS listener:

| Method/path | Purpose |
|---|---|
| `GET /api/state` | Catalog, profiles, system telemetry and instances |
| `POST /api/models/scan` | Discover local GGUF files |
| `POST /api/models` | Add/update a model, HF card, default launch |
| `GET /api/models/{id}` | Model header and estimated file size |
| `GET /api/fit?profile=rocm-0&ctx=8192` | Advisory memory estimate |
| `POST /api/instances` | Launch instance from JSON specification |
| `POST /api/instances/{name}/stop` | Drain or force-stop (`{"force":false}`) |
| `GET /api/instances/{name}/logs` | Tail latest logs |
| `POST /api/scenes` | Save named JSON launch set |
| `POST /api/scenes/save-running` | Save current running set |
| `POST /api/scenes/{name}/apply` | Start entire saved set |

All POST requests require `X-Prollama-Request: 1` and application-level Basic auth (on TCP). You can automate the API with `curl --cacert`, e.g.:

```bash
curl --cacert prollama-ca.crt -u admin:YOUR_ADMIN_PASSWORD \
  -H 'X-Prollama-Request: 1' -H 'Content-Type: application/json' \
  -d '{"name":"small-cpu","model_id":"llama-8b","profile":"cpu","public_port":8082,"launch":{"gpu_layers":0,"threads":16,"ctx_size":8192}}' \
  https://llama.home.arpa:8443/api/instances
```

## Operation and troubleshooting

```bash
sudo systemctl status prollama-pie nginx --no-pager
sudo journalctl -u prollama-pie -n 150 --no-pager
sudo /usr/sbin/nginx -t
sudo ss -ltnp | grep -E ':(8443|8080|18080|18765)\b'
sudo -u prollama /opt/prollama-pie/venv/bin/prollama doctor
sudo -u prollama /opt/prollama-pie/venv/bin/prollama logs INSTANCE_NAME
```

**`502 Bad Gateway`:** model is loading/crashed or wrong backend port; inspect `prollama ps` and model logs. **Nginx refuses to reload:** check `nginx -t`, port collisions, cert readability and error log. **GPU telemetry empty:** ROCm sysfs entries absent or not readable, `nvidia-smi` missing, or user lacks privileges; see `rocm-smi` and `journalctl`. **`Permission denied` to GPU:** ensure system `prollama` is member of appropriate `render`/`video` groups, verify `/dev/kfd` and `/dev/dri/*`, and restart the supervisor for new group membership. **GGUF found but won't start:** confirm executable has required backend/features, `llama-server --help`, file permissions, quantization architecture and free memory. **HTTPS hostname mismatch:** regenerate certificate with correct SAN, install it and reload nginx; trust the private CA on client.

**Systemd:** `KillMode=process` is intentional: only the supervisor receives normal service stop signals; child llama-server processes continue running, and the next supervisor instance reattaches by PID and process creation timestamp. To terminate models intentionally, use CLI `down`. **Restarting only the daemon should not stop a working model stream.** But shutting down the entire machine or killing a llama-server process will.

## Security notes

- Bind llama-server instances to loopback. Only nginx terminates TLS; don't use a local listener on `0.0.0.0` for an unencrypted llama-server.
- Limit publicly accessible frontend ports with both nginx configuration and a firewall. Use a VPN for off-LAN access.
- Use nontrivial admin credentials and llama.cpp API-key files. Some upstream endpoints don't require the API key; consider separate front-end authentication if clients can be untrusted. The management dashboard does **not** proxy arbitrary commands to a shell.
- The nginx helper is invoked as root through one exact sudoers command, not general `systemctl` privileges. Files in `/opt/prollama-pie` and root settings must remain **root-owned and not writable by prollama**. Do not give group members unrestricted write access to code files or nginx TLS private key.
- Each process launches with an argv list, not `/bin/sh -c`, reducing shell injection; however, trusted admins can configure extra llama.cpp flags and arbitrary local GGUF paths. Treat access to admin UI/Unix socket as powerful local process-management access.
- Audit Python dependencies, validate TLS configuration, set backup/secret-rotation procedures, and perform real load tests before production rollout.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
pytest -q
# For a nonprivileged dev run, create a real local binary, config.json,
# and set nginx_apply_command to [] (nginx routes will NOT be configured).
PRO_LLAMA_CONFIG=./config.local.json prollama-daemon
```

Project layout:

```text
prollama-pie/
├── pro_llama/
│   ├── supervisor.py      # process launch/recovery, health, draining, scenes
│   ├── daemon.py          # authenticated dashboard + JSON/Unix socket API
│   ├── cli.py             # human and JSON CLI
│   ├── nginx_apply.py     # root-side restricted nginx config renderer/reloader
│   ├── hardware.py        # AMD/NVIDIA VRAM + CPU RAM inventory
│   ├── gguf.py            # GGUF metadata and approximate KV sizing
│   ├── common.py          # input validation and atomic JSON storage
│   └── static/            # standalone web UI: HTML/CSS/JS
├── config/                # example daemon and root helper config
├── cert/generate_cert.sh  # SAN-aware local CA + leaf cert generator
├── deploy/                # root installer + systemd unit
├── docs/                  # operational notes and roadmap
└── tests/                 # unit and smoke tests
```

## Limitations and operational guarantees

**Implemented in v0.1:** one-host multi-instance execution; allowed public/backend pool separation; dynamic nginx HTTPS listeners with restricted graceful reloads; JSON persistence; PID/create-time recovery; health polling; optional metrics reading; model scanning/cards; rough GGUF/KV fit; AMD/NVIDIA/CPU telemetry; profiles; scenes; browser controls; drain-first stop; CLI; Linux systemd installation.

**Not claimed as completed:** cross-host orchestration, automatic exact model/GPU placement, account-based RBAC, process cgroups or resource quotas, live actual per-instance VRAM attribution, intelligent speculative acceptance benchmarks, HF card auto-download, runtime feature negotiation for arbitrary llama.cpp versions, Windows server installation, automatic certificate renewal, full high-availability failover, or an absolutely infallible no-interruption guarantee for outside process crashes/hard restarts. See `docs/ROADMAP.md`.

## References

- [llama.cpp llama-server arguments and HTTP API](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [llama.cpp speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md)
- [nginx graceful reload semantics](https://nginx.org/en/docs/beginners_guide.html)
- [nginx proxy buffering / timeout directives](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)
- [nginx TLS settings](https://nginx.org/en/docs/http/ngx_http_ssl_module.html)

## License

MIT, see [LICENSE](LICENSE). `llama.cpp`, GGUF models, model cards and ROCm/NVIDIA drivers are external projects with their own licenses.
