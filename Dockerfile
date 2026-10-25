# Build du frontend (Vite) puis image Python qui sert API + frontend + Chainlit.
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=frontend /frontend/dist ./frontend/dist

# Le code range ses données à côté de lui (BASE_DIR) : on les redirige vers
# /data, qui est le seul volume à persister. Chainlit lit .chainlit/ et écrit
# .files/ dans le répertoire courant.
RUN mkdir /data \
 && ln -s /data/notes.db notes.db \
 && ln -s /data/conversations.db conversations.db \
 && ln -s /data/models models \
 && ln -s /data/.files .files

EXPOSE 8300
CMD ["sh", "-c", "mkdir -p /data/models /data/.files && exec uvicorn app:app --host 0.0.0.0 --port 8300"]
