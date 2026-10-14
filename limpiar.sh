#!/usr/bin/env bash
# Elimina contenedores, red, volumen de datos e imagen de App_Parcial1.
# No toca ningún otro recurso de Docker del equipo (por ejemplo, los del parcial).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [[ "${1:-}" != "-y" ]]; then
    read -r -p "Se borrarán la base de datos y los cambios hechos desde la GUI. ¿Continuar? [s/N] " r
    [[ "$r" =~ ^[sS]$ ]] || { echo "Cancelado."; exit 0; }
fi

docker compose down -v --remove-orphans
docker image rm app_parcial1-app:latest 2>/dev/null || true
echo "Recursos de App_Parcial1 eliminados."
