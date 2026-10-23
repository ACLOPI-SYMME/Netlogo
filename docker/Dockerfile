# ACLOPI simulation platform: headless NetLogo 6.4.0 + Python 3.12 + aclopi.
# Build from the repository root:
#   docker build -f docker/Dockerfile -t aclopi-sim .
FROM python:3.12-slim-bookworm

# Official NetLogo 6.4.0 Linux release, direct link from https://www.netlogo.org/downloads/archive/6.4.0
# The checksum matches the one GitHub publishes for the same file (release v6.4.0).
ARG NETLOGO_URL=https://downloads.netlogo.org/6.4.0/NetLogo-6.4.0-64.tgz
# Alternative (same file, same checksum):
# ARG NETLOGO_URL=https://github.com/NetLogo/NetLogo/releases/download/v6.4.0/NetLogo-6.4.0-64.tgz
ARG NETLOGO_SHA256=8647223b4282e0be3e62dc9c45207f82410ba63dd2892b08af2940cbaa6ad1de

# Same variables as .env on Windows; the JVM is the one bundled with NetLogo.
# JAVA_TOOL_OPTIONS reaches every JVM, including those started by scripts that do not use
# SimulationSession. ACLOPI_JVM_ARGS (e.g. "-Xmx768m") is passed by SimulationSession.
ENV NETLOGO_HOME=/opt/netlogo \
    JVM_PATH=/opt/netlogo/lib/runtime/lib/server/libjvm.so \
    JAVA_TOOL_OPTIONS="-Djava.awt.headless=true" \
    ACLOPI_JVM_ARGS="" \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl procps \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "$NETLOGO_URL" -o /tmp/netlogo.tgz \
    && echo "$NETLOGO_SHA256  /tmp/netlogo.tgz" | sha256sum -c - \
    && mkdir -p "$NETLOGO_HOME" \
    && tar -xzf /tmp/netlogo.tgz -C "$NETLOGO_HOME" --strip-components=1 \
    && rm /tmp/netlogo.tgz \
    && test -f "$JVM_PATH"

RUN useradd --create-home --uid 1000 aclopi
WORKDIR /app

COPY requirements.txt pyproject.toml ./
RUN pip install -r requirements.txt
COPY aclopi ./aclopi
RUN pip install --no-deps -e .

COPY pytest.ini ./
COPY model ./model
COPY scripts ./scripts
COPY tests ./tests
RUN mkdir -p results model/Results/Data model/Results/Events && chown -R aclopi:aclopi /app

USER aclopi
CMD ["python", "scripts/smoke_test.py"]
