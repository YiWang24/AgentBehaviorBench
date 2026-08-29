# Layer the benchmark worker on top of the UNMODIFIED upstream image.
#
# Build the base first, straight from the vendored source, with no edits:
#   docker build -t ta-native:a33fd4c ./TradingAgents
#
# Keeping the upstream Dockerfile as the base is what preserves "native":
# tradingagents and all of its dependencies are installed exactly as the
# project ships them, and nothing under TradingAgents/ is patched.
ARG BASE_IMAGE=ta-native:a33fd4c
FROM ${BASE_IMAGE}

USER root
COPY bench/ /opt/bench/
RUN chown -R appuser:appuser /opt/bench
USER appuser

# ABB's docker runtime appends launch.argv to the image ENTRYPOINT rather than
# replacing it, so the upstream ENTRYPOINT ["tradingagents"] would swallow the
# worker command as stray CLI arguments. Reset it here, in our layer, so the
# upstream Dockerfile still needs no edits.
ENTRYPOINT []

WORKDIR /opt/agent
