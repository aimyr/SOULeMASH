FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scraper_worker.py sync_listener.py supervisord.conf ./

# supervisor запускает оба процесса
CMD ["/usr/bin/supervisord", "-c", "supervisord.conf"]
