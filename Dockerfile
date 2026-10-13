FROM python:3.12-slim
WORKDIR /app
COPY server.py ./
COPY public ./public
RUN useradd --uid 10001 --create-home ddl && mkdir /app/data && chown ddl:ddl /app/data
USER ddl
ENV DDL_HOST=0.0.0.0 DDL_PORT=8080 DDL_DATA_DIR=/app/data PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "server.py"]
