#!/bin/bash
# CustomGPTs Container Entrypoint
#
# Runs before supervisord to prepare the container environment:
#   1. Create data directories for browser profile and images
#   2. Clean stale Chromium lock files from previous container runs
#   3. Set up VNC password if VNC_PASSWORD environment variable is set
#   4. Launch supervisord to start all managed processes
set -e

echo "=== CustomGPTs Container Starting ==="

# ── Ensure data directories exist ─────────────────────────────
# These are within the bind-mounted volume (./.customgpts on host)
mkdir -p /root/.customgpts/profile
mkdir -p /root/.customgpts/images

# ── Clean stale Chromium lock files from previous container ───
# When the container is stopped/killed, Chromium doesn't clean up its lock files.
# These persist on the host via bind mount and block Chromium from starting
# on the next container launch. Safe to remove — no running Chromium at this point.
rm -f /root/.customgpts/profile/SingletonLock \
      /root/.customgpts/profile/SingletonCookie \
      /root/.customgpts/profile/SingletonSocket

# ── Set VNC password if provided ──────────────────────────────
# If VNC_PASSWORD is set (via docker-compose.yml or .env), create an encrypted
# password file and pass VNC_ARGS to x11vnc via supervisord's %(ENV_VNC_ARGS)s.
if [ -n "$VNC_PASSWORD" ]; then
    mkdir -p /root/.vnc
    x11vnc -storepasswd "$VNC_PASSWORD" /root/.vnc/passwd
    export VNC_ARGS="-rfbauth /root/.vnc/passwd"
    echo "VNC password set."
else
    export VNC_ARGS=""
    echo "VNC running without password (set VNC_PASSWORD to secure)."
fi

# ── Register DNS routes for cloudflared tunnel ──────────────────
# Auto-creates CNAME records in Cloudflare DNS so the tunnel hostnames resolve.
# Uses cert.pem (mounted from ~/.cloudflared/) for API authentication.
# --overwrite-dns prevents errors if the records already exist.
if [ -f /etc/cloudflared/cert.pem ] && [ -f /etc/cloudflared/creds.json ]; then
    TUNNEL_ID=$(grep -o '"TunnelID":"[^"]*"' /etc/cloudflared/creds.json | cut -d'"' -f4)
    if [ -n "$TUNNEL_ID" ]; then
        echo "Registering DNS routes for tunnel $TUNNEL_ID..."
        cloudflared tunnel --origincert /etc/cloudflared/cert.pem route dns --overwrite-dns "$TUNNEL_ID" customgpts.rohitsoni.com || true
        cloudflared tunnel --origincert /etc/cloudflared/cert.pem route dns --overwrite-dns "$TUNNEL_ID" vnc.rohitsoni.com || true
        echo "DNS routes registered."
    fi
else
    echo "Skipping DNS route registration (cert.pem or creds.json not found)."
fi

# ── Launch supervisord ────────────────────────────────────────
# exec replaces this shell process with supervisord (PID 1).
# supervisord then manages all child processes (xvfb, x11vnc, novnc, customgpts, cloudflared).
echo "=== Starting supervisord ==="
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
