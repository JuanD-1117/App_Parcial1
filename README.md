# App_Parcial1 — GW Explorer

Aplicación completa sobre una base de datos relacional con GUI en Streamlit, construida sobre el
Primer Parcial de Desarrollo de Software 2026.

**Juan Diego Martínez Ayala** · Fuente de datos: [GWOSC — Gravitational Wave Open Science Center](https://gwosc.org)

Contiene los eventos de ondas gravitacionales registrados por LIGO, Virgo y KAGRA en los catálogos
GWTC-1, GWTC-2.1 y GWTC-3 (campañas O1 a O3b, 2015–2020), con estos datos por evento:

- masas
- distancia
- SNR
- detectores participantes
- tiempo GPS/UTC
- archivos de strain publicados

## Guía de exposición

[`docs/Guia_App_Parcial1.pdf`](docs/Guia_App_Parcial1.pdf) (40 páginas) explica el proyecto desde
cero: la física, el modelo de datos, el diseño de la app y cada pantalla, con un guion para
exponerlo, una demostración paso a paso, preguntas probables y un glosario. La fuente LaTeX está en
`docs/guia/` y se compila con `latexmk -pdf guia_app.tex`.

Cada módulo se puede abrir directamente por URL: `http://localhost:8502/?modulo=analisis`
(`inicio`, `dashboard`, `explorador`, `analisis`, `detectores`, `consultas`, `crud`).

## Arquitectura

```
┌──────────────┐     red Docker app_parcial1_red      ┌──────────────────┐
│  app         │ ───────────── host "mysql" ─────────▶│  mysql (8.4)     │
│  Streamlit   │                                      │  base gwosc      │
│  :8502       │      ┌──────────────┐                │  :3308 anfitrión │
└──────────────┘      │  carga       │ ──────────────▶│  volumen         │
                      │  (una vez)   │                │  app_parcial1_   │
                      └──────────────┘                │  mysql           │
                                                      └──────────────────┘
```

| Servicio | Qué hace |
|---|---|
| `mysql` | MySQL 8.4. La primera vez aplica `db/schema.sql`, que crea 8 tablas, 3 vistas, claves foráneas y `CHECK` |
| `carga` | Inserta `data/*.csv` (1327 filas) en una sola transacción y verifica los recuentos. Si la base ya tiene datos, no hace nada, así que reiniciar no borra lo editado en la GUI |
| `app` | La GUI Streamlit. Arranca solo cuando la carga terminó con éxito |

## Uso

Requisito: Docker Desktop (o Docker Engine con `docker compose` v2).

```bash
git clone https://github.com/JuanD-1117/App_Parcial1.git
cd App_Parcial1
./instalar.sh
```

Abra **http://localhost:8502**.

| Comando | Efecto |
|---|---|
| `./instalar.sh` | Construye y levanta todo. Se puede repetir sin riesgo |
| `./instalar.sh --reiniciar` | Además recarga los datos originales y descarta los cambios hechos con el CRUD |
| `docker compose down` | Detiene los contenedores y conserva los datos |
| `./limpiar.sh` | Borra contenedores, volumen e imagen de este proyecto, y nada más |

Los puertos por defecto son 3308 (MySQL) y 8502 (app), distintos de los del parcial (3307), así
que ambos proyectos pueden correr a la vez. Para cambiarlos:

```bash
APP_PORT=8600 MYSQL_PORT=3310 ./instalar.sh
```

También puede copiar `.env.example` a `.env`.

### Ejecutar la app fuera de Docker

Con MySQL levantado por `./instalar.sh`:

```bash
pip install -r requirements-dev.txt
cd app && streamlit run app.py      # se conecta a localhost:3308
```

## Módulos de la GUI

| Módulo | Contenido |
|---|---|
| 🏠 **Inicio** | Qué es una onda gravitacional y qué es el strain; la pregunta científica; el modelo relacional con el recuento de filas de cada tabla |
| 📊 **Dashboard** | Indicadores; detecciones acumuladas; eventos por campaña y tipo; m₁ frente a m₂; distancia frente a masa de chirp; resumen estadístico. Cada gráfico explica cómo leerlo |
| 🔭 **Explorador** | Tabla filtrable y descargable en CSV. Ficha de cada evento: parámetros con su intervalo al 90 %, masas con barras de error, detectores, archivos de strain y enlace a GWOSC |
| 🧪 **Análisis científico** | Las tres sub-preguntas del parcial, calculadas en vivo: (a) hueco PISN, (b) sesgo de selección con la curva de horizonte 𝓜 ∝ d^(6/5), (c) evolución entre campañas. Incluye la conclusión |
| 📡 **Detectores y strain** | Mapa de la red, participaciones por campaña, archivos de strain por detector, y qué es el strain y por qué no se reanaliza |
| 🗄️ **Consultas SQL** | Las 20 consultas de `db/consultas.sql` (de básicas a funciones de ventana) y una consola de solo lectura |
| ✏️ **Gestión de datos (CRUD)** | Crear, editar y borrar eventos, mediciones y participaciones evento–detector |

**Filtros de la barra lateral**, que se aplican a Dashboard, Explorador y Análisis:
- campaña
- tipo de fuente
- detector que observó el evento
- masa total
- distancia
- SNR mínima
- clasificación ambigua

### Sobre el strain

El strain h(t) es la serie de tiempo que mide cada interferómetro. El análisis del parcial no la
usa: la pregunta es sobre la población de fuentes, y los parámetros del catálogo ya son el
resultado de analizar el strain mediante *matched filtering* e inferencia bayesiana. La app sí
muestra el strain como dato de procedencia. `participacion.archivos_strain` guarda cuántos
archivos publicó GWOSC por evento y detector, y cada ficha enlaza a la página del evento en GWOSC
para descargarlos.

### Validación del CRUD

Cada escritura pasa por dos capas.

**1. Reglas físicas de la app** (`app/fisica.py`):
- El nombre tiene formato `GWaammdd[_hhmmss]` y su fecha coincide con el tiempo GPS.
- La campaña y la fecha UTC se calculan a partir del GPS, descontando los 18 s intercalares.
- Cada parámetro respeta su rango físico: masas > 0, |χ_eff| ≤ 1, 0 ≤ p_astro ≤ 1.
- El intervalo de credibilidad contiene al valor central.
- Se cumple la convención m₂ ≤ m₁, una regla entre filas que un `CHECK` no puede expresar.

**2. Restricciones de MySQL**, cuyos errores se traducen a mensajes legibles:
- `UNIQUE` (1062)
- claves foráneas (1452)
- `CHECK` (3819)
- `ON DELETE CASCADE` y `ON DELETE RESTRICT`

La consola SQL corre en una transacción `READ ONLY`, por lo que MySQL rechaza cualquier escritura.

## Estructura

```
App_Parcial1/
├── instalar.sh / limpiar.sh     # punto de entrada y limpieza
├── docker-compose.yml           # mysql + carga + app
├── .env.example
├── app/
│   ├── app.py                   # GUI Streamlit (solo interfaz)
│   ├── datos.py                 # acceso a datos: lecturas y CRUD, SQL parametrizada
│   ├── fisica.py                # reglas físicas y conversión GPS→UTC (lógica pura)
│   ├── consultas.py             # lee db/consultas.sql
│   ├── cargar_datos.py          # carga transaccional e idempotente de data/
│   ├── Dockerfile
│   └── requirements.txt
├── db/
│   ├── schema.sql               # esquema del parcial (3FN, 8 tablas, 3 vistas)
│   └── consultas.sql            # 20 consultas de análisis
├── data/                        # 7 tablas limpias del parcial (CSV)
└── tests/                       # 35 pruebas: física, consultas e integración con MySQL
```

## Pruebas

```bash
pip install -r requirements-dev.txt
pytest tests -v
```

- `test_fisica.py` comprueba la conversión GPS→UTC contra la fecha publicada de GW150914, la
  asignación de campañas y que los 90 eventos y las 969 mediciones del catálogo pasan la
  validación.
- `test_consultas.py` comprueba la lectura de las 20 consultas.
- `test_integracion.py` ejecuta el CRUD completo contra el MySQL de Docker y deja la base como la
  encontró. Se omite si la base no está levantada.

## Resultados que reproduce la app

Las cifras coinciden con el informe del parcial:

- **Hueco PISN**: la densidad de eventos por M☉ cae × 5.8 por encima de 45 M☉.
- **Sesgo de selección**: la masa de chirp mínima crece con el cuartil de distancia.
- **Campañas**: de O1 a O3b la tasa de detección se multiplica por 10.2 y el alcance pasa de
  1000 a 7100 Mpc, mientras la SNR mediana baja de 12.7 a 10.4.
