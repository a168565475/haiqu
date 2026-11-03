# CODEX_IMAGE由部署者核对现有固定0.165.0镜像后显式传入，不下载或升级CLI。
ARG CODEX_IMAGE
FROM ${CODEX_IMAGE} AS verified_codex
FROM public.ecr.aws/docker/library/python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/runtime
COPY --from=verified_codex /usr/local/bin/codex /usr/local/bin/codex
COPY --from=verified_codex /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY src/codex_runtime/ /opt/runtime/codex_runtime/
COPY src/codex_runtime/config.toml /etc/codex/config.toml
RUN mkdir -p /work/current /run/haiqu-codex /state/codex \
    && chown -R 10001:10001 /work/current /run/haiqu-codex /state/codex \
    && chmod 0700 /state/codex /work/current \
    && chmod 0770 /run/haiqu-codex
USER 10001:10001
ENTRYPOINT ["python", "-B", "-m", "codex_runtime"]
