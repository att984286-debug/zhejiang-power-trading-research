ARG BASE_IMAGE=python:3.12.15-slim
FROM ${BASE_IMAGE}
WORKDIR /app
COPY requirements.txt requirements-runtime.txt requirements-test.txt ./
RUN pip install --no-cache-dir --index-url https://pypi.org/simple -r requirements.txt -r requirements-test.txt && pip check
COPY . .
EXPOSE 8501
CMD ["python", "-m", "streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
