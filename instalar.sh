#!/usr/bin/env bash
# Levanta App_Parcial1 completa: MySQL 8.4, carga de datos y GUI Streamlit.
#
#   ./instalar.sh                 # construye y levanta (idempotente)
#   ./instalar.sh --reiniciar     # además recarga los datos originales (borra cambios del CRUD)
#
# Puertos por defecto: MySQL 3308, app 8502. Se cambian en .env o al llamar:
#   APP_PORT=8600 MYSQL_PORT=3310 ./instalar.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

error() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
paso()  { printf '\n==> %s\n' "$*"; }

command -v docker >/dev/null 2>&1 || error "Docker no está instalado: https://docs.docker.com/get-docker/"
docker info >/dev/null 2>&1 || error "El daemon de Docker no responde. Abra Docker Desktop."
docker compose version >/dev/null 2>&1 || error "Falta el plugin 'docker compose' (v2)."

# Las variables de .env tienen prioridad más baja que las del entorno, igual que en compose.
if [[ -f .env ]]; then
    set -a; source .env; set +a
fi
APP_PORT="${APP_PORT:-8502}"
MYSQL_PORT="${MYSQL_PORT:-3308}"
export APP_PORT MYSQL_PORT

puerto_ocupado_por_otro() {
    local puerto="$1"
    # Un puerto ocupado por los propios contenedores del proyecto no es un conflicto.
    if docker ps --filter "name=app_parcial1-" --format '{{.Ports}}' | grep -q ":${puerto}->"; then
        return 1
    fi
    lsof -iTCP:"$puerto" -sTCP:LISTEN -P -n >/dev/null 2>&1
}
for par in "APP_PORT:$APP_PORT" "MYSQL_PORT:$MYSQL_PORT"; do
    nombre="${par%%:*}"; puerto="${par##*:}"
    if command -v lsof >/dev/null 2>&1 && puerto_ocupado_por_otro "$puerto"; then
        error "El puerto $puerto está en uso. Use otro: $nombre=<puerto> ./instalar.sh"
    fi
done

paso "Construyendo la imagen y levantando MySQL -> carga -> app..."
docker compose up -d --build mysql app

if [[ "${1:-}" == "--reiniciar" ]]; then
    paso "Recargando los datos originales (se descartan los cambios hechos desde la GUI)..."
    docker compose run --rm carga python cargar_datos.py --reiniciar
else
    paso "Resultado de la carga:"
    docker compose logs --no-log-prefix carga | tail -n 12
fi

paso "Esperando a que la app responda en http://localhost:$APP_PORT ..."
for _ in $(seq 1 60); do
    if curl -fsS "http://localhost:$APP_PORT/_stcore/health" >/dev/null 2>&1; then
        break
    fi
    sleep 2
done
curl -fsS "http://localhost:$APP_PORT/_stcore/health" >/dev/null 2>&1 \
    || error "La app no respondió. Revise: docker compose logs app"

docker compose ps
cat <<FIN

  App Streamlit : http://localhost:$APP_PORT
  MySQL         : localhost:$MYSQL_PORT  base gwosc, usuario ${MYSQL_USER:-gwuser}

  Detener (conserva datos) : docker compose down
  Borrar todo              : ./limpiar.sh
FIN

if command -v open >/dev/null 2>&1; then
    open "http://localhost:$APP_PORT" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://localhost:$APP_PORT" >/dev/null 2>&1 || true
fi
