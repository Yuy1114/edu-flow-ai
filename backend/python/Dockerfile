FROM python:3.13-slim

WORKDIR /workspace/backend/python

# lightgbm links against the OpenMP runtime; python:slim does not ship it and
# the import fails at startup with "libgomp.so.1: cannot open shared object
# file". app.api.v1.health imports the placement model at module load, so this
# is required even for a rules-only run.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy installable packages before building the local wheel.
COPY pyproject.toml .
COPY app/ ./app/
COPY scheduler/ ./scheduler/
COPY ingest/ ./ingest/
RUN pip install --no-cache-dir hatchling && pip install --no-cache-dir .

ENV PYTHONPATH=/workspace/backend/python
ENV EDU_FLOW_SIMULATION_DIR=/var/lib/edu-flow-ai/simulations
ENV EDU_FLOW_PIPELINE_LOG_DIR=/var/lib/edu-flow-ai/pipeline-jobs

EXPOSE 8000

CMD [ "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000" ]
