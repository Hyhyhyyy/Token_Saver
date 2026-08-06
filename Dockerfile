FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY skillforge ./skillforge
COPY frontend ./frontend

ENV SKILLS_DIRS=/root/.workbuddy/skills
ENV DATA_DIR=/app/data
VOLUME ["/root/.workbuddy/skills", "/app/data"]

EXPOSE 8000

CMD ["uvicorn", "skillforge.server:app", "--host", "0.0.0.0", "--port", "8000"]
