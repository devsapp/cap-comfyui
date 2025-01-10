FROM python:3.10.16-slim

WORKDIR /root
ENV WORK_DIR='/root'
ENV MNT_DIR='/mnt/auto'

COPY . agent/

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    python3 -m venv agent/venv

RUN --mount=type=cache,target=/root/.cache/pip \
    agent/venv/bin/pip install -r agent/requirements.txt --no-cache-dir

RUN chmod +x agent/entrypoint.bash
ENTRYPOINT [ "/bin/bash", "-c", "agent/entrypoint.bash" ]
