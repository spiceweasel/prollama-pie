# Security policy

## Deployment suitability

The current 0.1.0 release is a **public alpha**, intended for trusted Linux hosts and LANs. It is **not** hardened or independently audited for public-Internet exposure. No user-level role-based permissions exist; anyone able to administer instances can run llama.cpp with local model paths and profile environments.

## Security design

- Separate privileged nginx helper from unprivileged process supervisor; do not run the daemon as root.
- Install source/venv and nginx helper root-owned. Never grant `prollama` write access to its root-executed Python module or root proxy settings.
- Management web endpoint requires HTTP Basic inside HTTPS; the local Unix socket uses filesystem permissions.
- Public model endpoints use `--api-key-file` by default. Some llama.cpp endpoints do not require model API keys; the generated nginx config denies several diagnostic endpoints directly.
- Generated nginx config consists only of validated integer port numbers, root-configured certificate paths, root-configured server names, and static directives. Routes are not interpolated from model-provided arbitrary nginx text.
- Normal route updates validate syntax and use graceful reload; no hard nginx restarts.
- Users are responsible for network firewall and CA certificate handling.

## Reporting

Before making a vulnerability public, contact the repository maintainer privately using GitHub's **Report a vulnerability** feature (enable private security advisories after publishing the repository). Do not include live secret keys, administrative passwords or confidential model files in an issue.

## Operational checklist

- Pin and update Python dependencies and llama.cpp builds after verification.
- Keep `/opt/pro-llama-server`, `/etc/pro-llama-server/proxy-settings.json`, nginx TLS keys, and sudoers configuration root-owned.
- Change/rotate administrator and model API keys; consider a local VPN rather than Internet exposure.
- Restrict ports 8080-8120/8443 or your configured public ranges to trusted networks.
- Never copy a local CA **private key** to client machines. Protect your backup of it or keep it offline.
- Evaluate SELinux/AppArmor and distro-specific restrictions before enabling GPU access.
- Test `systemctl reload nginx` (not `restart`) with your own nginx process configuration and sustained SSE workloads.
