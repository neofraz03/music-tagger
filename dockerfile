FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV MUSIC_DIR=/music

EXPOSE 5000

ENTRYPOINT ["python", "app.py"]