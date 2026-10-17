# Roadmap and design constraints

## v0.1 shipping boundary

- One daemon per Linux host, no remote RPC process control, SQLite server, database installation, Docker or Node build.
- JSON remains a single-writer store, with atomic save. Systemd manages daemon uniqueness in supported deployment.
- Per-port nginx HTTPS listeners dynamically generated via root helper, `nginx -t`, graceful reload, previous file restoration on failure.
- No automatic model downloads, no guarantee that VRAM estimates predict actual allocations.

## Recommended improvements before claiming 1.0

1. End-to-end integration tests with real llama-server processes and a dedicated nginx test instance, including long-lived streamed SSE requests during nginx reload; test ROCm and CUDA versions specifically.
2. Active-request accounting independent of connection status (nginx log instrumentation or a lightweight backend connection tracker), and a restart-safe drain state machine that gracefully handles keep-alives across nginx generations.
3. Runtime per-build capability probe (`--help`, `--version`) and flag adaptors for older llama.cpp releases.
4. Multi-instance single-host scheduling with per-GPU memory reservations, model-specific tensor-split estimation, draft model residency, memory fragmentation and running process reservations.
5. Rate-limited/federated metrics, model token throughput charts, opt-in metrics authentication, Prometheus export, and precise GPU index mapping via PCI IDs.
6. Browser UI settings editor for per-model presets, card URLs and GPU profile management with schema validation; confirmation for changing active model identity.
7. Cgroup-based CPU/memory isolation, restart policies, logs rotation, scene rollback for all side effects, and immutable launch profile snapshots.
8. Optional OIDC/mTLS and nginx front-end bearer validation for all endpoints, rather than relying on llama.cpp auth behavior on each route.
9. CA renewal or ACME workflows and security regression testing across Linux distributions including SELinux (Fedora).
10. One-to-many remote supervisors with independent trust/cert domains and a coordinating control plane, if multi-host becomes a core goal.

## Hard requirements and why they matter

**No nginx restart on route changes**: `nginx -s reload` / `systemctl reload nginx` uses generation rollover. A host-level hard restart, worker timeout, or backend process kill is outside this guarantee.

**Backend port allocation**: ports are probed when allocating, then released before `llama-server` binds (a small time-of-check/time-of-use race). In future, pass inherited sockets if llama-server gains socket activation, or monitor for collisions and retry cleanly before nginx attaches.

**Graceful drain**: removing a listener from the next nginx generation does not close the old generation's established streams. The backend must survive while old workers use it. Detection via psutil TCP `ESTABLISHED` states is conservative but not equivalent to accurate HTTP request accounting. No fixed timeout should force-kill active streams.

**No database installation**: JSON is convenient, but consistent concurrent writes require a single daemon. Lock the state directory on daemon startup, never share the state directory over unreliable NFS, and back it up atomically.

**Default security**: admin Basic over HTTPS, Unix socket perms, API-key-file for llama.cpp, root-owned static helper, restricted LAN only. Build/test a comprehensive threat model before WAN exposure.
