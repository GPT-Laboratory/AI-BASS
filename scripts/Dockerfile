FROM python:3.10-slim
WORKDIR /app
COPY testdata.py .
COPY init_db.py .
COPY wait-for-it.sh .
RUN apt-get update && apt-get install -y netcat-openbsd && rm -rf /var/lib/apt/lists/*
RUN chmod +x wait-for-it.sh
RUN pip install pymongo openai requests
CMD ["python", "init_db.py"]
