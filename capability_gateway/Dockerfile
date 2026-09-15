FROM python:3.12.11-alpine3.22

RUN apk add --no-cache openssl \
    && addgroup -S hermeteam \
    && adduser -S -G hermeteam -h /opt/hermeteam hermeteam \
    && mkdir -p /opt/hermeteam/capability_gateway /opt/data \
    && chown -R hermeteam:hermeteam /opt/hermeteam /opt/data

WORKDIR /opt/hermeteam
COPY --chown=hermeteam:hermeteam . /opt/hermeteam/capability_gateway

ENV PYTHONPATH=/opt/hermeteam \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CAPABILITY_GATEWAY_BIND=0.0.0.0 \
    CAPABILITY_GATEWAY_PORT=8787

USER hermeteam
EXPOSE 8787

CMD ["python", "-m", "capability_gateway.service"]
