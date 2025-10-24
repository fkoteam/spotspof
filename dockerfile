# Stage 1: Build frontend (React)
FROM node:18 AS build-frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install
COPY src/ ./src/
COPY public/ ./public/
RUN npm run build  # Genera /build/ con static files

# Stage 2: Backend Python + copia frontend build
FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install yt-dlp && \
    apt-get update && apt-get install -y ffmpeg && apt-get clean
COPY app.py .
COPY --from=build-frontend /app/build ./build  # Copia build de React
EXPOSE 5000
CMD ["python", "app.py"]
