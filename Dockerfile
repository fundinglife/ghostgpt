# CustomGPTs Docker Image
#
# Multi-stage build that creates a container running:
#   1. Xvfb       — Virtual display for Chromium (no physical monitor needed)
#   2. x11vnc     — VNC server for remote browser access (login, debugging)
#   3. noVNC      — Browser-based VNC client at port 6080
#   4. customgpts — API server at port 5124
#   5. cloudflared — Cloudflare tunnel for external HTTPS access
#
# The browser profile, config, and downloaded images persist via a bind mount
# at /root/.customgpts (mapped to ./.customgpts on the host).
#
# Build: docker compose build
# Run:   docker compose up -d
# Login: Open http://localhost:6080 (noVNC) and log into ChatGPT

# ── Stage 1: Build ──────────────────────────────────────────────
# Install the Python package and download Chromium in a build stage
# to keep the final image smaller (no build tools in runtime).
FROM python:3.12-slim-bookworm AS builder

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install the customgpts package and its dependencies
RUN pip install --no-cache-dir .
# Download the Chromium browser binary used by patchright
RUN patchright install chromium

# ── Stage 2: Runtime ────────────────────────────────────────────
# Slim runtime image with only the dependencies needed to run.
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    # Virtual display & VNC — provides a headless X11 display for Chromium
    xvfb \
    x11vnc \
    novnc \
    websockify \
    supervisor \
    # Clipboard support — required for clipboard-paste input method
    xclip \
    # Chromium runtime dependencies — shared libraries required by the Chromium binary
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    libgtk-3-0 \
    fonts-liberation \
    fonts-noto-color-emoji \
    # curl is only needed to download cloudflared, then purged
    curl \
    && curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb \
    && dpkg -i cloudflared.deb \
    && rm cloudflared.deb \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages and CLI entrypoint from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=builder /usr/local/bin/customgpts /usr/local/bin/customgpts
COPY --from=builder /usr/local/bin/patchright /usr/local/bin/patchright
# Copy the downloaded Chromium browser binary from builder
COPY --from=builder /root/.cache/ms-playwright/ /root/.cache/ms-playwright/

# Copy supervisor config and container entrypoint script
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker/entrypoint.sh /entrypoint.sh
# Fix Windows CRLF line endings (if built on Windows) and make entrypoint executable
RUN sed -i 's/\r$//' /entrypoint.sh /etc/supervisor/conf.d/supervisord.conf \
    && chmod +x /entrypoint.sh

# Environment variables for the virtual display
ENV DISPLAY=:99
ENV DISPLAY_WIDTH=1280
ENV DISPLAY_HEIGHT=720
ENV VNC_PASSWORD=""

# Ports: 5124 = CustomGPTs API server, 6080 = noVNC web interface
EXPOSE 5124 6080

# Persistent storage for browser profile, config.json, and downloaded images
VOLUME /root/.customgpts

ENTRYPOINT ["/entrypoint.sh"]
