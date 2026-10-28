# The deployed app: the Next.js workbench plus the Python pipeline it drives.
#
# Both halves live in one image because lib/runner.ts spawns
# `python -m silicontruth.cli pipeline` as a subprocess. Splitting them would
# mean an RPC layer between two things that are already one program.
#
# The emulate gate is the reason this cannot run on Fargate. It shells out to
# `docker run` for the Renode container, which needs a Docker daemon;
# Fargate gives you neither a daemon nor privileged mode. So this image ships
# the docker CLI only, and the host's socket is mounted in at run time. The
# container never runs a daemon of its own.

# ---- web build ------------------------------------------------------------
FROM node:22-bookworm-slim AS web
WORKDIR /app/web

COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
# The replay routes are prerendered at build time from the recorded runs, so
# the fixtures have to be present before `next build`, not after.
COPY fixtures/ /app/fixtures/
RUN npm run build

# ---- runtime --------------------------------------------------------------
FROM node:22-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        ca-certificates curl gnupg \
    # docker CLI only. The daemon is the host's, reached through the mounted
    # socket; a daemon in here would be docker-in-docker and need privileged.
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
         -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
         > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The Python half, installed into a venv so it is not fighting the system
# interpreter Debian ships.
ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH
RUN python3 -m venv "$VIRTUAL_ENV"

COPY pyproject.toml README.md ./
COPY silicontruth/ ./silicontruth/
RUN pip install --no-cache-dir -e .

COPY fixtures/ ./fixtures/
COPY benchmarks/ ./benchmarks/

# The built web app. `next start` needs .next, public, node_modules and the
# manifest; copying the whole directory keeps that simple and the image is
# not size-critical here.
COPY --from=web /app/web /app/web

# runner.ts resolves the repo root as one level up from the Next cwd, which
# is why the app sits at /app/web with the Python package at /app.
WORKDIR /app/web

EXPOSE 3000
# A failing container should restart rather than serve 502s quietly.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/api/run').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["npx", "next", "start", "-H", "0.0.0.0", "-p", "3000"]
