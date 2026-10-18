#!/usr/bin/env bash
# Install on Linux with python3, venv, nginx, openssl and sudo preinstalled.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run sudo ./deploy/install.sh" >&2; exit 1; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
getent group prollama >/dev/null || groupadd --system prollama
id prollama &>/dev/null || useradd --system --gid prollama --home-dir /var/lib/prollama-pie --shell /usr/sbin/nologin prollama
for group in render video; do getent group "$group" >/dev/null && usermod -aG "$group" prollama || true; done
install -d -m 0755 /opt/prollama-pie
install -d -m 0755 /opt/prollama-pie/src
cp -a "$ROOT/prollama" "$ROOT/pyproject.toml" /opt/prollama-pie/src/
python3 -m venv /opt/prollama-pie/venv
/opt/prollama-pie/venv/bin/pip install --disable-pip-version-check /opt/prollama-pie/src
ln -sfn /opt/prollama-pie/venv/bin/prollama /usr/local/bin/prollama
chown -R root:root /opt/prollama-pie
install -d -m 0750 -o root -g prollama /etc/prollama-pie
install -d -m 0750 -o prollama -g prollama /var/lib/prollama-pie
if [ ! -f /etc/prollama-pie/config.json ]; then
  install -m 0640 -o root -g prollama "$ROOT/config/config.example.json" /etc/prollama-pie/config.json
fi
if [ ! -f /etc/prollama-pie/proxy-settings.json ]; then
  install -m 0600 -o root -g root "$ROOT/config/proxy-settings.example.json" /etc/prollama-pie/proxy-settings.json
fi
if [ ! -f /etc/prollama-pie/admin-password ]; then
  umask 077
  openssl rand -hex 24 > /etc/prollama-pie/admin-password
  chown root:prollama /etc/prollama-pie/admin-password
  chmod 0640 /etc/prollama-pie/admin-password
fi
if [ ! -f /etc/prollama-pie/model-keys ]; then
  umask 077
  openssl rand -hex 32 > /etc/prollama-pie/model-keys
  chown root:prollama /etc/prollama-pie/model-keys
  chmod 0640 /etc/prollama-pie/model-keys
fi
cat > /usr/local/sbin/prollama-nginx-apply <<'SCRIPT'
#!/bin/sh
set -eu
exec /opt/prollama-pie/venv/bin/python -m prollama.nginx_apply
SCRIPT
chmod 0755 /usr/local/sbin/prollama-nginx-apply
chown root:root /usr/local/sbin/prollama-nginx-apply
if command -v visudo >/dev/null; then
  echo 'prollama ALL=(root) NOPASSWD: /usr/local/sbin/prollama-nginx-apply' > /etc/sudoers.d/prollama-pie
  chmod 0440 /etc/sudoers.d/prollama-pie
  visudo -cf /etc/sudoers.d/prollama-pie
else
  echo "WARNING: visudo unavailable; configure root helper permissions manually" >&2
fi
install -m 0644 "$ROOT/deploy/prollama-pie.service" /etc/systemd/system/prollama-pie.service
systemctl daemon-reload
printf '\nInstalled. Before enabling service:\n'
printf '  1) Edit /etc/prollama-pie/config.json with the correct binary and model paths.\n'
printf '  2) Generate TLS credentials and install to /etc/nginx/ssl (README).\n'
printf '  3) sudo systemctl enable --now nginx\n'
printf '  4) sudo /usr/local/sbin/prollama-nginx-apply\n'
printf '  5) sudo systemctl enable --now prollama-pie\n'
printf '  6) Use sudo -u prollama /opt/prollama-pie/venv/bin/prollama ps\n'
printf 'Management password: sudo cat /etc/prollama-pie/admin-password\n'
