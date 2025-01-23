FROM python:3.10-slim

WORKDIR /app

COPY server.py .
COPY server_requirements.txt requirements.txt
COPY wsgi.py .

RUN pip install -r requirements.txt

EXPOSE 8765

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8765"]
