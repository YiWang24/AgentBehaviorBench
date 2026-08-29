# The KUMA layer, on top of the UNMODIFIED upstream image.
#
# kuma_bench.py builds the base first, straight from the vendored source with
# its own Dockerfile and no edits:
#
#     docker build -t ta-native:a33fd4c ./TradingAgents
#
# Keeping the upstream Dockerfile as the base is what preserves "native":
# tradingagents and every dependency is installed exactly as the project ships
# them, and nothing under TradingAgents/ is patched.
#
# This file is not built in place. kuma_bench.py stages a context holding this
# Dockerfile plus a copy of the KUMA SDK source, because kuma-defuzex is not on
# PyPI and the SDK checkout lives outside the agent directory.
ARG BASE_IMAGE=ta-native:a33fd4c
FROM ${BASE_IMAGE}

USER root

# The SDK, plus the OpenTelemetry extra. `kuma-defuzex[otel]` cannot be named
# here because the package is installed from a local path, so the extra's two
# dependencies are listed explicitly; they match the [otel] extra in the SDK's
# pyproject.toml.
COPY kuma-src /opt/kuma-src
RUN pip install --no-cache-dir /opt/kuma-src \
      "opentelemetry-api>=1.30,<2" \
      "opentelemetry-sdk>=1.30,<2" \
 && mkdir -p /out /opt/bench \
 && chown -R appuser:appuser /out /opt/bench

USER appuser

# ABB's docker runtime appends launch.argv to the image ENTRYPOINT rather than
# replacing it, so the upstream ENTRYPOINT ["tradingagents"] would swallow the
# driver command as stray CLI arguments. Reset it here, in our layer, so the
# upstream Dockerfile still needs no edits.
ENTRYPOINT []

WORKDIR /opt/agent
