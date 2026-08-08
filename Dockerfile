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

CMD ["gunicorn", "--bind", "0.0.0.0:80", "--workers", "3", "--timeout", "300", "app:app"]
