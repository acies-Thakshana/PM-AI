FROM python:3.11-slim

WORKDIR /opt/program

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV AIBI_PROJECT_ROOT=/opt/program \
    AIBI_LLM_MODE=local \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/program/lib/python:/opt/program

EXPOSE 8080

# SageMaker appends the command "serve". Extra arguments are ignored.
ENTRYPOINT ["python", "serve.py"]
CMD ["serve"]
