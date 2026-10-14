# Imagen única para la app Streamlit y para el servicio de carga inicial.
# Contexto de construcción: la raíz del proyecto (ver docker-compose.yml).
FROM python:3.12-slim

WORKDIR /proyecto

COPY app/requirements.txt app/requirements.txt
RUN pip install --no-cache-dir -r app/requirements.txt

COPY app/  app/
COPY db/   db/
COPY data/ data/

WORKDIR /proyecto/app
EXPOSE 8501

HEALTHCHECK --interval=10s --timeout=5s --retries=12 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", \
     "--server.headless=true", "--browser.gatherUsageStats=false"]
