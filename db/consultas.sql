-- =====================================================================================
--  Consultas de análisis sobre la base de datos gwosc
--  Autor : Juan Diego Martínez Ayala
--
--  Las consultas van de menor a mayor complejidad. Las de los niveles 1 a 5 muestran el
--  manejo del lenguaje; las del nivel 6 responden directamente a la pregunta científica:
--
--      ¿Cómo se distribuye la masa de los objetos compactos detectados, y en qué medida
--      esa distribución está moldeada por el sesgo de selección del instrumento en lugar
--      de por la astrofísica de las fuentes?
--
--  Ejecución completa:
--      docker compose exec -T mysql mysql -ugwuser -p... gwosc < sql/consultas.sql
-- =====================================================================================

USE gwosc;

-- -------------------------------------------------------------------------------------
--  NIVEL 1 — Consultas básicas
-- -------------------------------------------------------------------------------------

-- C1. Los diez eventos más lejanos observados.
--     El más lejano está a unos 8 Gpc: la señal viajó más de la mitad de la edad del universo.
SELECT      e.nombre, e.tipo_fuente, ROUND(m.valor) AS distancia_mpc, YEAR(e.utc) AS anio
FROM        evento    e
JOIN        medicion  m ON m.evento_id    = e.evento_id
JOIN        parametro p ON p.parametro_id = m.parametro_id
WHERE       p.nombre = 'luminosity_distance'
ORDER BY    m.valor DESC
LIMIT 10;

-- C2. Catálogo de parámetros con su unidad: la base documenta sus propias magnitudes.
SELECT      nombre, simbolo, unidad, descripcion
FROM        parametro
ORDER BY    unidad, nombre;

-- C3. Eventos cuya clasificación es ambigua: alguna componente entre 2 y 5 masas solares,
--     el llamado hueco de masa inferior. GW190814 es el caso discutido en la literatura.
SELECT      nombre, tipo_fuente, DATE(utc) AS fecha
FROM        evento
WHERE       clasificacion_ambigua = TRUE
ORDER BY    utc;

-- -------------------------------------------------------------------------------------
--  NIVEL 2 — Agregación y agrupamiento
-- -------------------------------------------------------------------------------------

-- C4. Cuántos eventos aportó cada catálogo y qué periodo cubre.
SELECT      c.nombre                AS catalogo,
            c.anio_publicacion,
            COUNT(e.evento_id)      AS eventos,
            MIN(DATE(e.utc))        AS primer_evento,
            MAX(DATE(e.utc))        AS ultimo_evento
FROM        catalogo c
LEFT JOIN   evento   e ON e.catalogo_id = c.catalogo_id
GROUP BY    c.catalogo_id, c.nombre, c.anio_publicacion
ORDER BY    c.anio_publicacion;

-- C5. Distribución por tipo de fuente, con la fracción sobre el total.
--     Las binarias de agujeros negros dominan: no porque sean más frecuentes en el universo,
--     sino porque son mucho más ruidosas y se ven desde más lejos.
SELECT      tipo_fuente,
            COUNT(*)                                          AS eventos,
            ROUND(100 * COUNT(*) / (SELECT COUNT(*) FROM evento), 1) AS porcentaje
FROM        evento
GROUP BY    tipo_fuente
ORDER BY    eventos DESC;

-- C6. Estadísticos de cada magnitud física, leyendo la unidad de la tabla de parámetros.
SELECT      p.nombre        AS parametro,
            p.unidad,
            COUNT(*)        AS n,
            ROUND(MIN(m.valor), 3)  AS minimo,
            ROUND(AVG(m.valor), 3)  AS media,
            ROUND(MAX(m.valor), 3)  AS maximo,
            ROUND(STDDEV_SAMP(m.valor), 3) AS desviacion
FROM        medicion  m
JOIN        parametro p ON p.parametro_id = m.parametro_id
GROUP BY    p.parametro_id, p.nombre, p.unidad
ORDER BY    p.nombre;

-- C7. Detectores que participaron en más de treinta eventos (HAVING sobre el agregado).
SELECT      d.sigla, d.nombre, d.longitud_brazo_m, COUNT(*) AS eventos
FROM        detector      d
JOIN        participacion pa ON pa.detector_id = d.detector_id
GROUP BY    d.detector_id, d.sigla, d.nombre, d.longitud_brazo_m
HAVING      COUNT(*) > 30
ORDER BY    eventos DESC;

-- -------------------------------------------------------------------------------------
--  NIVEL 3 — Combinaciones de varias tablas
-- -------------------------------------------------------------------------------------

-- C8. Composición de la red por evento: recorre las cinco tablas del núcleo del modelo.
--     Esta consulta es imposible sobre un archivo plano sin manipular cadenas de texto.
SELECT      red, COUNT(*) AS eventos
FROM  (
    SELECT  e.evento_id,
            GROUP_CONCAT(d.sigla ORDER BY d.sigla SEPARATOR '+') AS red
    FROM    evento        e
    JOIN    participacion pa ON pa.evento_id  = e.evento_id
    JOIN    detector      d  ON d.detector_id = pa.detector_id
    GROUP BY e.evento_id
) AS redes
GROUP BY    red
ORDER BY    eventos DESC;

-- C9. Eventos observados por la red completa H1+L1+V1, con sus masas.
--     Tres detectores permiten triangular la posición en el cielo.
SELECT      e.nombre,
            ROUND(m1.valor, 1) AS masa_1,
            ROUND(m2.valor, 1) AS masa_2,
            ROUND(md.valor)    AS distancia_mpc
FROM        evento    e
JOIN        medicion  m1 ON m1.evento_id = e.evento_id
JOIN        parametro p1 ON p1.parametro_id = m1.parametro_id AND p1.nombre = 'mass_1_source'
JOIN        medicion  m2 ON m2.evento_id = e.evento_id
JOIN        parametro p2 ON p2.parametro_id = m2.parametro_id AND p2.nombre = 'mass_2_source'
JOIN        medicion  md ON md.evento_id = e.evento_id
JOIN        parametro pd ON pd.parametro_id = md.parametro_id AND pd.nombre = 'luminosity_distance'
WHERE       (SELECT COUNT(*) FROM participacion pa WHERE pa.evento_id = e.evento_id) = 3
ORDER BY    m1.valor DESC
LIMIT 10;

-- C10. Configuración instrumental de cada campaña frente a los eventos que produjo.
SELECT      c.nombre                                             AS campana,
            c.fecha_inicio, c.fecha_fin,
            GROUP_CONCAT(DISTINCT d.sigla ORDER BY d.sigla)      AS detectores_activos,
            (SELECT COUNT(*) FROM evento e WHERE e.campana_id = c.campana_id) AS eventos
FROM        campana          c
JOIN        campana_detector cd ON cd.campana_id  = c.campana_id
JOIN        detector         d  ON d.detector_id  = cd.detector_id
GROUP BY    c.campana_id, c.nombre, c.fecha_inicio, c.fecha_fin
ORDER BY    c.fecha_inicio;

-- -------------------------------------------------------------------------------------
--  NIVEL 4 — Subconsultas y expresiones de tabla comunes
-- -------------------------------------------------------------------------------------

-- C11. Eventos cuya masa primaria supera la media del catálogo (subconsulta escalar).
SELECT      e.nombre, ROUND(m.valor, 1) AS masa_1
FROM        evento    e
JOIN        medicion  m ON m.evento_id = e.evento_id
JOIN        parametro p ON p.parametro_id = m.parametro_id AND p.nombre = 'mass_1_source'
WHERE       m.valor > (SELECT AVG(m2.valor)
                       FROM   medicion  m2
                       JOIN   parametro p2 ON p2.parametro_id = m2.parametro_id
                       WHERE  p2.nombre = 'mass_1_source')
ORDER BY    m.valor DESC
LIMIT 10;

-- C12. Detectores que nunca observaron una fusión de estrellas de neutrones (NOT EXISTS).
SELECT      d.sigla, d.nombre, d.pais
FROM        detector d
WHERE       NOT EXISTS (
                SELECT 1
                FROM   participacion pa
                JOIN   evento        e ON e.evento_id = pa.evento_id
                WHERE  pa.detector_id = d.detector_id
                  AND  e.tipo_fuente  = 'BNS');

-- C13. Los eventos más energéticos, usando una CTE para aislar el cálculo.
--      La energía radiada es la diferencia entre la masa total y la del remanente.
WITH energia AS (
    SELECT  e.evento_id,
            e.nombre,
            MAX(CASE WHEN p.nombre = 'total_mass_source' THEN m.valor END) AS masa_total,
            MAX(CASE WHEN p.nombre = 'final_mass_source' THEN m.valor END) AS masa_final
    FROM    evento    e
    JOIN    medicion  m ON m.evento_id    = e.evento_id
    JOIN    parametro p ON p.parametro_id = m.parametro_id
    WHERE   e.masa_total_origen = 'publicado'
    GROUP BY e.evento_id, e.nombre
)
SELECT      nombre,
            ROUND(masa_total, 1)                          AS masa_total,
            ROUND(masa_total - masa_final, 2)             AS energia_radiada_msun,
            ROUND(100 * (masa_total - masa_final) / masa_total, 1) AS porcentaje_radiado
FROM        energia
WHERE       masa_final IS NOT NULL
ORDER BY    energia_radiada_msun DESC
LIMIT 10;

-- -------------------------------------------------------------------------------------
--  NIVEL 5 — Funciones de ventana
-- -------------------------------------------------------------------------------------

-- C14. Los tres eventos más masivos de cada campaña, con su posición dentro del grupo.
WITH ordenados AS (
    SELECT  c.nombre AS campana,
            e.nombre AS evento,
            m.valor  AS masa_1,
            RANK() OVER (PARTITION BY c.campana_id ORDER BY m.valor DESC) AS puesto
    FROM    evento    e
    JOIN    campana   c ON c.campana_id   = e.campana_id
    JOIN    medicion  m ON m.evento_id    = e.evento_id
    JOIN    parametro p ON p.parametro_id = m.parametro_id AND p.nombre = 'mass_1_source'
)
SELECT      campana, puesto, evento, ROUND(masa_1, 1) AS masa_1
FROM        ordenados
WHERE       puesto <= 3
ORDER BY    campana, puesto;

-- C15. Mediana de la SNR por campaña. MySQL no tiene PERCENTILE_CONT, de modo que se
--      construye con funciones de ventana: se numeran las filas por campaña y se toma la
--      central (o el promedio de las dos centrales si el conteo es par).
WITH snr AS (
    SELECT  c.nombre AS campana,
            m.valor  AS snr,
            ROW_NUMBER() OVER (PARTITION BY c.campana_id ORDER BY m.valor) AS fila,
            COUNT(*)     OVER (PARTITION BY c.campana_id)                  AS total
    FROM    evento    e
    JOIN    campana   c ON c.campana_id   = e.campana_id
    JOIN    medicion  m ON m.evento_id    = e.evento_id
    JOIN    parametro p ON p.parametro_id = m.parametro_id AND p.nombre = 'snr_red'
)
SELECT      campana,
            MAX(total)              AS eventos,
            ROUND(AVG(snr), 2)      AS snr_mediana
FROM        snr
WHERE       fila IN (FLOOR((total + 1) / 2), FLOOR((total + 2) / 2))
GROUP BY    campana
ORDER BY    campana;

-- C16. Detecciones acumuladas en el tiempo: suma corrida sobre la línea temporal.
SELECT      DATE(utc)                                          AS fecha,
            nombre                                             AS evento,
            COUNT(*) OVER (ORDER BY utc)                       AS acumuladas
FROM        evento
ORDER BY    utc
LIMIT 12;

-- -------------------------------------------------------------------------------------
--  NIVEL 6 — Consultas que responden la pregunta científica
-- -------------------------------------------------------------------------------------

-- C17. SUB-PREGUNTA (a): ¿hay supresión de eventos en el hueco de masa por inestabilidad
--      de pares? Se compara la densidad de eventos por unidad de masa dentro y fuera de la
--      ventana 45-120 M_sun. Si el hueco existiera, la densidad interior sería muy inferior.
-- El ancho de cada región se calcula en la CTE: agrupar directamente sobre una expresión
-- que usa columnas no agregadas choca con sql_mode=only_full_group_by, que MySQL 8 activa
-- por defecto y que conviene no desactivar: obliga a escribir agrupamientos sin ambigüedad.
WITH clasificadas AS (
    SELECT  m.valor AS masa,
            CASE
                WHEN m.valor <  45 THEN 'A. Por debajo del hueco (0-45)'
                WHEN m.valor < 120 THEN 'B. Dentro del hueco PISN (45-120)'
                ELSE                    'C. Por encima del hueco (>120)'
            END AS region,
            CASE
                WHEN m.valor <  45 THEN 45
                WHEN m.valor < 120 THEN 75
                ELSE 1
            END AS ancho_msun
    FROM    medicion  m
    JOIN    parametro p ON p.parametro_id = m.parametro_id
    WHERE   p.nombre = 'mass_1_source'
)
SELECT      region,
            COUNT(*)                                   AS eventos,
            ROUND(MIN(masa), 1)                        AS masa_minima,
            ROUND(MAX(masa), 1)                        AS masa_maxima,
            MAX(ancho_msun)                            AS ancho_msun,
            ROUND(COUNT(*) / MAX(ancho_msun), 3)       AS eventos_por_masa_solar
FROM        clasificadas
GROUP BY    region
ORDER BY    region;

-- C18. SUB-PREGUNTA (b): ¿crece la masa de chirp con la distancia? Se divide la muestra en
--      cuartiles de distancia y se compara la masa de chirp mínima de cada uno. La amplitud
--      escala como M^(5/6)/d_L, de modo que la masa mínima detectable debe crecer con d_L.
WITH resumen AS (
    SELECT  r.evento,
            r.masa_chirp,
            r.distancia_mpc,
            NTILE(4) OVER (ORDER BY r.distancia_mpc) AS cuartil
    FROM    v_evento_resumen r
    WHERE   r.masa_chirp IS NOT NULL AND r.distancia_mpc IS NOT NULL
)
SELECT      cuartil,
            COUNT(*)                          AS eventos,
            ROUND(MIN(distancia_mpc))         AS dl_min,
            ROUND(MAX(distancia_mpc))         AS dl_max,
            ROUND(MIN(masa_chirp), 2)         AS chirp_minima,
            ROUND(AVG(masa_chirp), 2)         AS chirp_media
FROM        resumen
GROUP BY    cuartil
ORDER BY    cuartil;

-- C19. SUB-PREGUNTA (c): ¿mejoró la sensibilidad entre campañas? Se comparan la tasa de
--      detección, la SNR media y el alcance. La firma de una mejora instrumental es más
--      eventos y mayor distancia, no mayor SNR: un detector más sensible alcanza un volumen
--      mayor y la mayoría de los eventos nuevos llegan justo por encima del umbral.
SELECT      c.nombre                                                   AS campana,
            COUNT(DISTINCT e.evento_id)                                AS eventos,
            DATEDIFF(c.fecha_fin, c.fecha_inicio)                      AS dias,
            ROUND(30.4 * COUNT(DISTINCT e.evento_id)
                  / DATEDIFF(c.fecha_fin, c.fecha_inicio), 2)          AS eventos_por_mes,
            ROUND(AVG(CASE WHEN p.nombre = 'snr_red' THEN m.valor END), 2)             AS snr_media,
            ROUND(AVG(CASE WHEN p.nombre = 'luminosity_distance' THEN m.valor END))    AS distancia_media,
            ROUND(MAX(CASE WHEN p.nombre = 'luminosity_distance' THEN m.valor END))    AS alcance_maximo
FROM        campana   c
JOIN        evento    e ON e.campana_id   = c.campana_id
JOIN        medicion  m ON m.evento_id    = e.evento_id
JOIN        parametro p ON p.parametro_id = m.parametro_id
GROUP BY    c.campana_id, c.nombre, c.fecha_inicio, c.fecha_fin
ORDER BY    c.fecha_inicio;

-- C20. Síntesis: el sesgo de selección en una sola tabla. Para cada rango de masa de chirp
--      se calcula la distancia máxima a la que se ha detectado un evento. Si la detección no
--      estuviera sesgada, el alcance sería independiente de la masa.
SELECT      CASE
                WHEN masa_chirp <  10 THEN 'chirp < 10'
                WHEN masa_chirp <  25 THEN 'chirp 10-25'
                WHEN masa_chirp <  40 THEN 'chirp 25-40'
                ELSE                       'chirp > 40'
            END                                  AS rango_masa_chirp,
            COUNT(*)                             AS eventos,
            ROUND(AVG(distancia_mpc))            AS distancia_media_mpc,
            ROUND(MAX(distancia_mpc))            AS alcance_maximo_mpc,
            ROUND(AVG(snr_red), 1)               AS snr_media
FROM        v_evento_resumen
WHERE       masa_chirp IS NOT NULL
GROUP BY    rango_masa_chirp
ORDER BY    alcance_maximo_mpc;
