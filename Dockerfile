FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home nexus
COPY app.py futures_app.py futures_engine.py futures_worker.py ./
COPY deploy ./deploy
RUN mkdir -p /app/runtime && chown -R nexus:nexus /app
USER nexus
ENV FUTURES_DATA_DIR=/app/runtime PYTHONUNBUFFERED=1
EXPOSE 8501
CMD ["python", "deploy/start.py"]
