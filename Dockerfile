FROM node:24-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
ENV HF_HUB_OFFLINE=1
COPY data/seed data/seed
COPY data/tests data/tests
COPY src src
COPY --from=web /app/web/dist web/dist
WORKDIR /app/src
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
