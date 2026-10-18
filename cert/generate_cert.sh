#!/usr/bin/env bash
# Generate a local private CA plus server certificate with correct DNS/IP SANs.
# Usage: ./cert/generate_cert.sh llama.home.arpa [192.168.1.20] [/tmp/pro-llama-pki]
set -euo pipefail
if [ "$#" -lt 1 ]; then echo "usage: $0 HOSTNAME [SERVER_IP] [OUTPUT_DIR]" >&2; exit 2; fi
HOST="$1"; IP="${2:-}"; OUT="${3:-./cert/output}"
[[ "$HOST" =~ ^[A-Za-z0-9.-]+$ ]] || { echo "invalid hostname" >&2; exit 2; }
if [[ -n "$IP" && ! "$IP" =~ ^[0-9a-fA-F.:]+$ ]]; then echo "invalid IP" >&2; exit 2; fi
umask 077
mkdir -p "$OUT"
CAKEY="$OUT/pro-llama-ca.key"; CACRT="$OUT/pro-llama-ca.crt"
KEY="$OUT/prollama-pie.key"; CSR="$OUT/prollama-pie.csr"; CRT="$OUT/prollama-pie.crt"
if [[ -e "$CAKEY" || -e "$KEY" || -e "$CACRT" ]]; then echo "refusing to overwrite existing cert/key files in $OUT" >&2; exit 1; fi
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$CAKEY"
openssl req -new -x509 -key "$CAKEY" -sha256 -days 3650 -out "$CACRT" \
  -subj "/CN=prollama-pie Local CA" -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" -addext "subjectKeyIdentifier=hash"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$KEY"
openssl req -new -key "$KEY" -out "$CSR" -subj "/CN=$HOST"
SAN="DNS:$HOST"
if [[ -n "$IP" ]]; then SAN=",IP:$IP"; SAN="DNS:$HOST$SAN"; fi
cat > "$OUT/server.ext" <<END
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = $SAN
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer
END
openssl x509 -req -in "$CSR" -CA "$CACRT" -CAkey "$CAKEY" -CAcreateserial \
  -out "$CRT" -days 397 -sha256 -extfile "$OUT/server.ext"
chmod 600 "$CAKEY" "$KEY"; chmod 644 "$CACRT" "$CRT"
rm -f "$CSR" "$OUT/server.ext"
echo "Generated server cert: $CRT"
echo "Generated server key: $KEY"
echo "Import ONLY this public CA into client trust stores: $CACRT"
echo "Keep the CA private key $CAKEY OFF client machines and ideally offline."
