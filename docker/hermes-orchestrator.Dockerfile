ARG HERMES_BASE_IMAGE=nousresearch/hermes-agent:latest
FROM ${HERMES_BASE_IMAGE}

USER root
ARG SUPERCRONIC_VERSION=v0.2.33
ARG TARGETARCH
RUN set -eux; \
    arch="${TARGETARCH:-amd64}"; \
    case "${arch}" in amd64) supercronic_arch=amd64 ;; arm64) supercronic_arch=arm64 ;; *) echo "unsupported arch: ${arch}" >&2; exit 1 ;; esac; \
    curl -fsSL "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${supercronic_arch}" -o /usr/local/bin/supercronic; \
    chmod 0755 /usr/local/bin/supercronic

COPY orchestrator /opt/hermes-sdlc-orchestrator
RUN chmod 0755 /opt/hermes-sdlc-orchestrator/bin/*.sh
ENV PYTHONPATH=/opt/hermes-sdlc-orchestrator
ENTRYPOINT ["/opt/hermes-sdlc-orchestrator/bin/container-entrypoint.sh"]
