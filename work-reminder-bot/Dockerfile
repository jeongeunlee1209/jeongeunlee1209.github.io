FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 TZ=Asia/Seoul
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py .
VOLUME ["/app/data"]
CMD ["python", "bot.py"]
