FROM python:3.12.11-alpine3.22
RUN addgroup -S hermeteam && adduser -S -G hermeteam -h /opt/hermeteam hermeteam
WORKDIR /opt/hermeteam
COPY --chown=hermeteam:hermeteam . /opt/hermeteam/subscription_gateway
USER hermeteam
ENV PYTHONPATH=/opt/hermeteam PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8085
CMD ["python", "-m", "subscription_gateway.server"]
