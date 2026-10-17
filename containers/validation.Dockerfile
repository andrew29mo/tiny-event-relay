FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
WORKDIR /workspace
COPY workspace /workspace
RUN python -m pip install --no-cache-dir -r requirements-dev.txt \
    && useradd --uid 10001 --create-home validator \
    && mkdir /evidence && chown -R validator:validator /workspace /evidence
USER validator
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-m", "tools.validate"]
