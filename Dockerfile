FROM python:3.11-slim

WORKDIR /app

COPY ./requirements.txt ./
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

COPY ./app.py ./database_controller.py ./mcp_server.py ./agent.py ./
COPY ./templates ./templates
COPY ./static ./static
COPY .env ./.env

# MySQL runs on the Docker host. 172.17.0.1 is the default bridge gateway.
# load_dotenv() does not override already-set env vars, so this wins over .env's host=127.0.0.1.
ENV host=172.17.0.1

# Single gthread worker with threads (NOT multiple sync workers): MCP SSE
# sessions live in process memory, so the SSE stream and the messages POSTs
# must share one process. Threads keep concurrency (SSE streams + long chat
# calls + web UI) without splitting session state across processes.
CMD ["gunicorn", "--bind", "0.0.0.0:80", "--worker-class", "gthread", "--workers", "1", "--threads", "16", "--timeout", "300", "app:app"]
