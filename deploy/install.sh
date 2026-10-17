#!/usr/bin/env bash
# Install on Linux with python3, venv, nginx, openssl and sudo preinstalled.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run sudo ./deploy/install.sh" >&2; exit 1; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
getent group prollama >/dev/null || groupadd --system prollama
id prollama &>/dev/null || useradd --system --gid prollama --home-dir /var/lib/pro-llama-server --shell /usr/sbin/nologin prollama
for group in render video; do getent group "$group" >/dev/null && usermod -aG "$group" prollama || true; done
install -d -m 0755 /opt/pro-llama-server
install -d -m 0755 /opt/pro-llama-server/src
cp -a "$ROOT/pro_llama" "$ROOT/pyproject.toml" /opt/pro-llama-server/src/
python3 -m venv /opt/pro-llama-server/venv
/opt/pro-llama-server/venv/bin/pip install --disable-pip-version-check /opt/pro-llama-server/src
chown -R root:root /opt/pro-llama-server
install -d -m 0750 -o root -g prollama /etc/pro-llama-server
install -d -m 0750 -o prollama -g prollama /var/lib/pro-llama-server
if [ ! -f /etc/pro-llama-server/config.json ]; then
  install -m 0640 -o root -g prollama "$ROOT/config/config.example.json" /etc/pro-llama-server/config.json
fi
if [ ! -f /etc/pro-llama-server/proxy-settings.json ]; then
  install -m 0600 -o root -g root "$ROOT/config/proxy-settings.example.json" /etc/pro-llama-server/proxy-settings.json
fi
if [ ! -f /etc/pro-llama-server/admin-password ]; then
  umask 077
  openssl rand -hex 24 > /etc/pro-llama-server/admin-password
  chown root:prollama /etc/pro-llama-server/admin-password
  chmod 0640 /etc/pro-llama-server/admin-password
fi
if [ ! -f /etc/pro-llama-server/model-keys ]; then
  umask 077
  openssl rand -hex 32 > /etc/pro-llama-server/model-keys
  chown root:prollama /etc/pro-llama-server/model-keys
  chmod 0640 /etc/pro-llama-server/model-keys
fi
cat > /usr/local/sbin/pro-llama-nginx-apply <<'SCRIPT'
#!/bin/sh
set -eu
exec /opt/pro-llama-server/venv/bin/python -m pro_llama.nginx_apply
SCRIPT
chmod 0755 /usr/local/sbin/pro-llama-nginx-apply
chown root:root /usr/local/sbin/pro-llama-nginx-apply
if command -v visudo >/dev/null; then
  echo 'prollama ALL=(root) NOPASSWD: /usr/local/sbin/pro-llama-nginx-apply' > /etc/sudoers.d/pro-llama-server
  chmod 0440 /etc/sudoers.d/pro-llama-server
  visudo -cf /etc/sudoers.d/pro-llama-server
else
  echo "WARNING: visudo unavailable; configure root helper permissions manually" >&2
fi
install -m 0644 "$ROOT/deploy/pro-llama-server.service" /etc/systemd/system/pro-llama-server.service
systemctl daemon-reload
printf '\nInstalled. Before enabling service:\n'
printf '  1) Edit /etc/pro-llama-server/config.json with the correct binary and model paths.\n'
printf '  2) Generate TLS credentials and install to /etc/nginx/ssl (README).\n'
printf '  3) sudo systemctl enable --now nginx\n'
printf '  4) sudo /usr/local/sbin/pro-llama-nginx-apply\n'
printf '  5) sudo systemctl enable --now pro-llama-server\n'
printf '  6) Use sudo -u prollama /opt/pro-llama-server/venv/bin/pro-llama ps\n'
printf 'Management password: sudo cat /etc/pro-llama-server/admin-password\n'
