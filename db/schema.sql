-- =====================================================================================
--  Proyecto : Sistema de gestión y análisis de datos de ondas gravitacionales (GWOSC)
--  Autor    : Juan Diego Martínez Ayala
--  Curso    : Primer Parcial - Desarrollo de Software 2026
--  Motor    : MySQL 8.4
--
--  Este archivo reconstruye la base de datos completa desde cero. Es idempotente: puede
--  ejecutarse sobre una instancia ya poblada y deja el esquema en su estado inicial.
--
--      docker compose exec -T mysql mysql -uroot -p$MYSQL_ROOT_PASSWORD < sql/schema.sql
--
--  El modelo se justifica en docs/05_modelo_relacional.pdf. En resumen: cinco entidades
--  (evento, detector, campana, catalogo, parametro) y tres tablas de relación que resuelven
--  otras tantas asociaciones de muchos a muchos.
-- =====================================================================================

DROP DATABASE IF EXISTS gwosc;
CREATE DATABASE gwosc
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;
USE gwosc;

-- -------------------------------------------------------------------------------------
--  1. Tablas de referencia
-- -------------------------------------------------------------------------------------

-- Publicaciones científicas que reportan eventos. Cada release es un reanálisis distinto
-- del mismo dato instrumental, con su propia referencia bibliográfica.
CREATE TABLE catalogo (
    catalogo_id       INT AUTO_INCREMENT PRIMARY KEY,
    nombre            VARCHAR(40)  NOT NULL UNIQUE COMMENT 'Release de GWOSC, p. ej. GWTC-3-confident',
    anio_publicacion  SMALLINT     NOT NULL,
    campanas_cubiertas VARCHAR(40) NOT NULL COMMENT 'Campañas que abarca la publicación',
    referencia        VARCHAR(200) NOT NULL COMMENT 'Cita bibliográfica completa',
    doi               VARCHAR(80)  UNIQUE,
    CONSTRAINT chk_catalogo_anio CHECK (anio_publicacion BETWEEN 2015 AND 2100)
) ENGINE=InnoDB COMMENT='Publicaciones oficiales de la colaboración LIGO-Virgo-KAGRA';

-- Periodos continuos de observación de la red.
CREATE TABLE campana (
    campana_id    INT AUTO_INCREMENT PRIMARY KEY,
    nombre        VARCHAR(8) NOT NULL UNIQUE COMMENT 'O1, O2, O3a, O3b',
    fecha_inicio  DATE NOT NULL,
    fecha_fin     DATE NOT NULL,
    CONSTRAINT chk_campana_fechas CHECK (fecha_fin > fecha_inicio)
) ENGINE=InnoDB COMMENT='Campañas de observación, con sus fechas oficiales';

-- Interferómetros. Existen con independencia de sus detecciones, de ahí que sean entidad
-- propia y no un atributo del evento.
CREATE TABLE detector (
    detector_id        INT AUTO_INCREMENT PRIMARY KEY,
    sigla              CHAR(2)      NOT NULL UNIQUE COMMENT 'H1, L1, V1, K1, G1',
    nombre             VARCHAR(40)  NOT NULL,
    pais               VARCHAR(40)  NOT NULL,
    latitud            DECIMAL(8,5) NOT NULL,
    longitud           DECIMAL(9,5) NOT NULL,
    longitud_brazo_m   SMALLINT     NOT NULL COMMENT 'Longitud del brazo del interferómetro, en metros',
    operador           VARCHAR(80)  NOT NULL,
    anio_inicio        SMALLINT     NOT NULL,
    CONSTRAINT chk_detector_latitud  CHECK (latitud  BETWEEN  -90 AND  90),
    CONSTRAINT chk_detector_longitud CHECK (longitud BETWEEN -180 AND 180),
    CONSTRAINT chk_detector_brazo    CHECK (longitud_brazo_m > 0)
) ENGINE=InnoDB COMMENT='Interferómetros de la red LIGO-Virgo-KAGRA y GEO 600';

-- Catálogo de magnitudes físicas. La unidad vive aquí y no en `medicion`: depende solo del
-- parámetro, que es la mitad de la clave compuesta de aquella tabla (dependencia parcial,
-- violación de 2FN).
CREATE TABLE parametro (
    parametro_id  INT AUTO_INCREMENT PRIMARY KEY,
    nombre        VARCHAR(40)  NOT NULL UNIQUE COMMENT 'Nombre de la columna en la fuente',
    simbolo       VARCHAR(16)  NOT NULL COMMENT 'Símbolo físico habitual',
    unidad        VARCHAR(20)  NOT NULL COMMENT 'M_sun, Mpc, 1/yr o adimensional',
    descripcion   VARCHAR(200) NOT NULL
) ENGINE=InnoDB COMMENT='Magnitudes medibles, con su unidad y significado físico';

-- -------------------------------------------------------------------------------------
--  2. Entidad central
-- -------------------------------------------------------------------------------------

-- Un evento es una coalescencia detectada. La clave primaria es surrogada y el nombre
-- público lleva UNIQUE: mantiene la garantía de unicidad con índices más compactos en las
-- tablas hijas, que son las que más filas tienen.
CREATE TABLE evento (
    evento_id             INT AUTO_INCREMENT PRIMARY KEY,
    nombre                VARCHAR(24)   NOT NULL UNIQUE COMMENT 'Nombre público, p. ej. GW150914',
    gwosc_id              VARCHAR(40)   NOT NULL COMMENT 'Identificador interno de la fuente',
    version               TINYINT       NOT NULL COMMENT 'Versión del reanálisis conservada',
    gps_tiempo            DECIMAL(16,4) NOT NULL COMMENT 'Instante de la fusión en tiempo GPS',
    utc                   DATETIME(3)   NOT NULL COMMENT 'Mismo instante en UTC, descontados 18 s intercalares',
    campana_id            INT           NOT NULL,
    catalogo_id           INT           NOT NULL,
    tipo_fuente           ENUM('BBH','NSBH','BNS') NOT NULL COMMENT 'Clasificación por masa respecto al límite TOV',
    clasificacion_ambigua BOOLEAN       NOT NULL DEFAULT FALSE
                          COMMENT 'Alguna componente en 2-5 M_sun: la clasificación no es concluyente',
    masa_total_origen     ENUM('publicado','derivado') NOT NULL DEFAULT 'publicado'
                          COMMENT 'Procedencia de la masa total; derivado significa reconstruida como m1+m2',
    referencia            VARCHAR(200),
    url_json              VARCHAR(255)  COMMENT 'Documento de la fuente del que salió el registro',

    CONSTRAINT fk_evento_campana  FOREIGN KEY (campana_id)  REFERENCES campana(campana_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_evento_catalogo FOREIGN KEY (catalogo_id) REFERENCES catalogo(catalogo_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT chk_evento_gps CHECK (gps_tiempo > 0),

    INDEX idx_evento_utc         (utc),
    INDEX idx_evento_campana     (campana_id),
    INDEX idx_evento_tipo_fuente (tipo_fuente)
) ENGINE=InnoDB COMMENT='Coalescencias de objetos compactos detectadas';

-- -------------------------------------------------------------------------------------
--  3. Tablas de relación
-- -------------------------------------------------------------------------------------

-- El valor de un parámetro para un evento. Formato largo: añadir una magnitud nueva es
-- insertar filas, no alterar el esquema. El CHECK del intervalo se declara una sola vez
-- para todos los parámetros; en un diseño de columnas anchas haría falta uno por trío.
CREATE TABLE medicion (
    evento_id     INT NOT NULL,
    parametro_id  INT NOT NULL,
    valor         DOUBLE NOT NULL,
    valor_min     DOUBLE COMMENT 'Cota inferior del intervalo de credibilidad al 90 %',
    valor_max     DOUBLE COMMENT 'Cota superior del intervalo de credibilidad al 90 %',

    PRIMARY KEY (evento_id, parametro_id),
    CONSTRAINT fk_medicion_evento    FOREIGN KEY (evento_id)    REFERENCES evento(evento_id)
        ON DELETE CASCADE  ON UPDATE CASCADE,
    CONSTRAINT fk_medicion_parametro FOREIGN KEY (parametro_id) REFERENCES parametro(parametro_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    -- El valor central debe caer dentro de su propio intervalo. Donde la fuente no publica
    -- cotas, ambas quedan NULL y la comparación no se evalúa.
    CONSTRAINT chk_medicion_intervalo CHECK (
        (valor_min IS NULL OR valor_min <= valor) AND
        (valor_max IS NULL OR valor <= valor_max)
    ),
    INDEX idx_medicion_parametro (parametro_id, valor)
) ENGINE=InnoDB COMMENT='Valor e intervalo de cada magnitud para cada evento';

-- Qué detectores aportaron datos a cada evento. Resuelve la relación de muchos a muchos
-- que hace imposible representar el conjunto en una sola tabla.
CREATE TABLE participacion (
    evento_id        INT NOT NULL,
    detector_id      INT NOT NULL,
    archivos_strain  SMALLINT COMMENT 'Número de productos de strain publicados para ese par',

    PRIMARY KEY (evento_id, detector_id),
    CONSTRAINT fk_participacion_evento   FOREIGN KEY (evento_id)   REFERENCES evento(evento_id)
        ON DELETE CASCADE  ON UPDATE CASCADE,
    CONSTRAINT fk_participacion_detector FOREIGN KEY (detector_id) REFERENCES detector(detector_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT chk_participacion_archivos CHECK (archivos_strain IS NULL OR archivos_strain >= 0),
    INDEX idx_participacion_detector (detector_id)
) ENGINE=InnoDB COMMENT='Relación evento-detector: qué instrumentos observaron cada fusión';

-- Qué detectores estuvieron activos en cada campaña. Evita guardar la lista como texto,
-- que sería una violación de 1FN introducida por el propio proyecto.
CREATE TABLE campana_detector (
    campana_id   INT NOT NULL,
    detector_id  INT NOT NULL,

    PRIMARY KEY (campana_id, detector_id),
    CONSTRAINT fk_campdet_campana  FOREIGN KEY (campana_id)  REFERENCES campana(campana_id)
        ON DELETE CASCADE  ON UPDATE CASCADE,
    CONSTRAINT fk_campdet_detector FOREIGN KEY (detector_id) REFERENCES detector(detector_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB COMMENT='Configuración instrumental de cada campaña';

-- -------------------------------------------------------------------------------------
--  4. Vistas
--
--  Las magnitudes derivadas no se almacenan: dependen de otras mediciones y guardarlas
--  como columnas sería una dependencia transitiva (violación de 3FN) que además permitiría
--  estados incoherentes. Una vista no puede desincronizarse de sus datos.
-- -------------------------------------------------------------------------------------

-- Los parámetros más consultados, ya pivotados. Da la comodidad del diseño de columnas
-- anchas sin renunciar a la flexibilidad del formato largo.
CREATE OR REPLACE VIEW v_evento_resumen AS
SELECT
    e.evento_id,
    e.nombre                AS evento,
    c.nombre                AS campana,
    cat.nombre              AS catalogo,
    e.utc,
    e.tipo_fuente,
    e.clasificacion_ambigua,
    MAX(CASE WHEN p.nombre = 'mass_1_source'       THEN m.valor END) AS masa_1,
    MAX(CASE WHEN p.nombre = 'mass_2_source'       THEN m.valor END) AS masa_2,
    MAX(CASE WHEN p.nombre = 'total_mass_source'   THEN m.valor END) AS masa_total,
    MAX(CASE WHEN p.nombre = 'chirp_mass_source'   THEN m.valor END) AS masa_chirp,
    MAX(CASE WHEN p.nombre = 'final_mass_source'   THEN m.valor END) AS masa_final,
    MAX(CASE WHEN p.nombre = 'luminosity_distance' THEN m.valor END) AS distancia_mpc,
    MAX(CASE WHEN p.nombre = 'redshift'            THEN m.valor END) AS corrimiento_al_rojo,
    MAX(CASE WHEN p.nombre = 'chi_eff'             THEN m.valor END) AS espin_efectivo,
    MAX(CASE WHEN p.nombre = 'snr_red'             THEN m.valor END) AS snr_red,
    MAX(CASE WHEN p.nombre = 'far'                 THEN m.valor END) AS tasa_falsa_alarma,
    MAX(CASE WHEN p.nombre = 'p_astro'             THEN m.valor END) AS p_astrofisico
FROM       evento    e
JOIN       campana   c   ON c.campana_id  = e.campana_id
JOIN       catalogo  cat ON cat.catalogo_id = e.catalogo_id
LEFT JOIN  medicion  m   ON m.evento_id   = e.evento_id
LEFT JOIN  parametro p   ON p.parametro_id = m.parametro_id
GROUP BY   e.evento_id, e.nombre, c.nombre, cat.nombre, e.utc, e.tipo_fuente, e.clasificacion_ambigua;

-- Magnitudes derivadas. El CASE traslada al esquema una regla física: la energía radiada no
-- se calcula cuando la masa total es reconstruida, porque restar una cantidad publicada de
-- una derivada dio -0.07 M_sun para GW170817 (ver docs/04_limpieza.pdf).
CREATE OR REPLACE VIEW v_magnitudes_derivadas AS
SELECT
    r.evento_id,
    r.evento,
    r.masa_2 / NULLIF(r.masa_1, 0)                       AS razon_masas,
    CASE WHEN e.masa_total_origen = 'publicado'
         THEN r.masa_total - r.masa_final
    END                                                  AS energia_radiada_msun,
    CASE WHEN e.masa_total_origen = 'publicado'
         THEN (r.masa_total - r.masa_final) / NULLIF(r.masa_total, 0)
    END                                                  AS fraccion_radiada,
    -- Frontera del horizonte de detección: M_chirp proporcional a d_L^(6/5).
    r.masa_chirp / POWER(NULLIF(r.distancia_mpc, 0), 1.2) AS indice_horizonte
FROM v_evento_resumen r
JOIN evento e ON e.evento_id = r.evento_id;

-- Composición de la red que observó cada evento, como cadena ordenada. Se calcula al
-- consultar; almacenarla sería justo la violación de 1FN que el modelo evita.
CREATE OR REPLACE VIEW v_red_por_evento AS
SELECT
    e.evento_id,
    e.nombre                                   AS evento,
    COUNT(pa.detector_id)                      AS n_detectores,
    GROUP_CONCAT(d.sigla ORDER BY d.sigla SEPARATOR '+') AS red
FROM       evento        e
JOIN       participacion pa ON pa.evento_id = e.evento_id
JOIN       detector      d  ON d.detector_id = pa.detector_id
GROUP BY   e.evento_id, e.nombre;
