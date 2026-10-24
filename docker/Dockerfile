# Build online; run scripts/verify-docker.sh with networking disabled.
FROM python:3.14.0-slim-bookworm@sha256:9bbb8720ae0a24a6ca8dd678bfdf57818fe70caf54c52a53ec01d8db43405056
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
# Build context contains a clean, standalone Git checkout at the documented pin.
COPY hermes-source /opt/hermes
RUN git config --system --add safe.directory /opt/hermes && \
    test "$(git -C /opt/hermes rev-parse HEAD)" = f42f579cf8bac4918ac9599bece71618afadd846 && \
    test -z "$(git -C /opt/hermes status --porcelain --untracked-files=all)"
COPY requirements-test.txt /opt/requirements-test.txt
RUN PYTHONPATH=/opt/hermes python -m pm.build_env --source /opt/hermes --export-requirements /opt/core-requirements.txt && \
    python -m venv /opt/runtime && \
    /opt/runtime/bin/python -m pip install --no-cache-dir -r /opt/core-requirements.txt -r /opt/requirements-test.txt ruff==0.14.2 && \
    chmod -R a+rX /opt/hermes
ENV PATH=/opt/runtime/bin:$PATH HOME=/scratch/home TMPDIR=/scratch PYTHONDONTWRITEBYTECODE=1 HERMES_AGENT_ROOT=/opt/hermes
USER 65532:65532
WORKDIR /source
CMD ["python3", "scripts/verify.py"]
