# Validación Técnica: Lakebase Autoscaling para E-Commerce Search & Recommendations

## Resumen Ejecutivo

Este documento recoge las respuestas y recomendaciones a las preguntas planteadas por el cliente sobre su despliegue de Lakebase Autoscaling para el buscador de su e-commerce, incluyendo validación del caso de uso, dimensionamiento, autenticación, permisos, arquitectura y migración desde CosmosDB.

**Conclusiones principales:**
- ✅ Lakebase Autoscaling **es la herramienta adecuada** para serving online de baja latencia
- ✅ La configuración de **1-2 CU** es razonable para el volumen actual
- ✅ El patrón **Service Principal + OAuth** es el oficialmente recomendado
- ✅ Las **funciones SQL/PLpgSQL** son un patrón válido para la capa de serving
- ✅ **Lakebase con pgvector** es mejor que Vector Search para su escala y necesidades
- ✅ La **migración desde CosmosDB** tiene sentido y es viable

---

## 1. Validación del Caso de Uso: ¿Es Lakebase adecuado para serving online?

### Respuesta: Sí, es un caso de uso explícitamente soportado

La documentación oficial de Databricks lista "Serve lakehouse data" como caso de uso primario de Lakebase. El producto está diseñado para:

> *"High QPS (1000s) of point operations at low-latency (<10ms)"*
> — FY27 Lakebase Field Guide

**Casos de uso validados para Lakebase:**
- Data serving: Serve insights from golden tables to applications at low latency and high QPS
- Feature serving: Serve featurized data at low latency to ML models
- Store application state: Manage workflow and agent state

**Relevancia para el cliente:**
- Catálogo de ~40.000 productos (volumen pequeño para Lakebase)
- ~3.000 productos por consulta (filtrado por distribuidor)
- Baja latencia requerida (serving desde backend e-commerce)
- pgvector disponible para búsquedas por similaridad

**Referencia:** [What is Lakebase Autoscaling?](https://docs.databricks.com/aws/en/oltp/projects/about)

---

## 2. Dimensionamiento: Configuración de CUs

### Especificaciones por CU (Lakebase Autoscaling)

| CU | RAM | Max Conexiones Concurrentes |
|----|-----|----------------------------|
| 0.5 | ~1 GB | 104 |
| 1 | ~2 GB | 209 |
| 2 | ~4 GB | 419 |
| 3 | ~6 GB | 629 |
| 4 | ~8 GB | 839 |

> **Nota importante:** En Lakebase Autoscaling, 1 CU = ~2 GB RAM. Esto es diferente de Lakebase Provisioned donde 1 CU = ~16 GB RAM.

### Rendimiento esperado (benchmarks internos)

- **YCSB point get:** ~1,700 – 20,000 filas de 1KB / CU (dependiendo de si los datos caben en caché)
- **Si datos caben en LFC (Local File Cache):** rendimiento significativamente mayor
- **Sync incremental:** ~1,200 filas/sec/CU

### Recomendación para el cliente

**Configuración recomendada en producción: 1-2 CU con autoscaling**

Justificación:
1. **Dataset en memoria:** 40K productos con embeddings de 768 dims ≈ 160MB → cabe sobradamente en 2 GB (1 CU)
2. **Conexiones:** 1 CU = 209 conexiones máx. Para un e-commerce con picos de tráfico, **2 CU (419 conexiones)** da más margen
3. **Coste:** 1 CU ≈ $3,500/año, 2 CU ≈ $7,000/año (pre-descuento) — muy razonable
4. **Rendimiento:** Con datos en caché (que es el caso), se alcanzan miles de QPS con 1 CU

### Scale-to-zero

| Entorno | Scale-to-zero | Timeout | Justificación |
|---------|--------------|---------|---------------|
| Dev | ✅ ON | 5 min | Ahorro de costes |
| Pre | ✅ ON | 30 min | Ahorro de costes |
| **Pro** | **❌ OFF** | N/A | Cold start ~500ms-2s inaceptable para e-commerce |

> **Cold start de Lakebase Autoscaling:** "a few hundred milliseconds" según docs oficiales; reportes de campo indican 500ms-2s. Lakebase es significativamente más rápido que Aurora Serverless v2 (~15s) o Azure PostgreSQL Flex (5+ min).

### Métricas a monitorizar

| Métrica | Herramienta | Umbral de alerta sugerido |
|---------|------------|--------------------------|
| QPS (Queries Per Second) | pg_stat_statements | Baseline + 50% |
| Latencia p50/p95/p99 | pg_stat_statements | p99 > 100ms |
| Conexiones activas | pg_stat_activity | > 80% del máximo |
| Cache hit ratio (LFC) | pg_stat_user_tables | < 95% |
| Autoscaling events | Lakebase Metrics Dashboard | Frecuencia alta = subdimensionado |
| Tamaño de respuesta | Application logs | > 1MB por query |

**Referencia:** [Manage computes](https://docs.databricks.com/aws/en/oltp/projects/manage-computes)

---

## 3. Autenticación: Service Principal + OAuth

### Respuesta: Es el patrón oficialmente recomendado

La documentación oficial de Databricks describe exactamente este flujo para aplicaciones externas.

### Flujo de autenticación

```
Backend E-Commerce
    │
    ├── 1. Service Principal (Entra ID) con OAuth secret
    │       └── Client ID + Client Secret (vida útil configurable, hasta 730 días)
    │
    ├── 2. Databricks SDK: generate_database_credential(endpoint=...)
    │       └── Genera token de base de datos (vida útil: 60 minutos)
    │
    ├── 3. Connection Pool (psycopg3 + ConnectionPool)
    │       └── Token refresh automático al crear nueva conexión
    │
    └── 4. Conexión PostgreSQL estándar (port 5432, SSL required)
            └── Ejecuta funciones SQL contra Lakebase
```

### Configuración del rol PostgreSQL

```sql
-- Habilitar extensión de autenticación
CREATE EXTENSION IF NOT EXISTS databricks_auth;

-- Crear rol OAuth usando el Client ID del Service Principal
SELECT databricks_create_role('{client-id}', 'SERVICE_PRINCIPAL');

-- Otorgar permisos de conexión
GRANT CONNECT ON DATABASE databricks_postgres TO "{client-id}";

-- Permisos por schema (principio de mínimo privilegio)
GRANT USAGE ON SCHEMA public TO "{client-id}";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO "{client-id}";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO "{client-id}";

-- Default privileges para futuros objetos
ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT SELECT ON TABLES TO "{client-id}";
ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT EXECUTE ON FUNCTIONS TO "{client-id}";
```

### Ejemplo de conexión (Python)

```python
import os
from databricks.sdk import WorkspaceClient
import psycopg
from psycopg_pool import ConnectionPool

workspace_client = WorkspaceClient(
    host=os.environ["DATABRICKS_HOST"],
    client_id=os.environ["DATABRICKS_CLIENT_ID"],
    client_secret=os.environ["DATABRICKS_CLIENT_SECRET"],
)

class OAuthConnection(psycopg.Connection):
    @classmethod
    def connect(cls, conninfo="", **kwargs):
        credential = workspace_client.postgres.generate_database_credential(
            endpoint=os.environ["ENDPOINT_NAME"]
        )
        kwargs["password"] = credential.token
        return super().connect(conninfo, **kwargs)

pool = ConnectionPool(
    conninfo=f"dbname={DB} user={USER} host={HOST} port=5432 sslmode=require",
    connection_class=OAuthConnection,
    min_size=1,
    max_size=10,
    open=True,
)

# Uso
with pool.connection() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM search_products_semantic(%s, %s, %s)", 
                    [query_embedding, distributor_id, 20])
        results = cur.fetchall()
```

**Dependencias:** `databricks-sdk>=0.89.0`, `psycopg[binary,pool]>=3.1.0`

**Referencia:** [Connect external app to Lakebase using SDK](https://docs.databricks.com/aws/en/oltp/projects/external-apps-connect)

---

## 4. Permisos para Synced Tables: Service Principal y Run As

### Problema

El Service Principal de Lakebase (SP-Lakebase) gestiona la infraestructura pero no tiene permisos sobre los esquemas de Unity Catalog necesarios para crear Synced Tables.

### Opciones evaluadas

| Opción | Descripción | Recomendación |
|--------|-------------|---------------|
| **A** | Dar permisos UC directamente a SP-Lakebase | ⚠️ Funcional pero no ideal |
| **B** | Run As con SP-Data que ya tiene permisos | ✅ **RECOMENDADA** |

### Recomendación: Opción B — Run As con SP dedicado a datos

**Justificación:**
1. **Separación de responsabilidades:** SP-Lakebase gestiona infraestructura; SP-Data gestiona acceso a datos
2. **Principio de mínimo privilegio:** cada SP tiene solo los permisos estrictamente necesarios
3. **Seguridad:** si un SP se compromete, el radio de impacto está contenido
4. **Auditabilidad:** separación clara de quién hizo qué
5. **Alineado con best practices de Databricks** para jobs de producción

### Implementación

#### Permisos necesarios para SP-Data (el "Run As"):

```
Unity Catalog:
├── SELECT en tablas fuente (catálogo de productos)
├── USE CATALOG en el catálogo fuente
├── USE SCHEMA en los esquemas fuente
├── CREATE TABLE en esquema destino (para la synced table)
└── Escritura en pipeline storage schema

Lakebase Project:
└── CAN USE en el proyecto Lakebase
```

#### Permisos necesarios para SP-Lakebase (owner del job):

```
Service Principal:
└── Rol "Service Principal User" sobre SP-Data
    (permite configurar Run As = SP-Data)

Job:
└── IS OWNER o CAN MANAGE en el job
```

#### Configuración del Job:

```yaml
# En el DAB (databricks.yml)
resources:
  jobs:
    sync_tables_job:
      name: "lakebase-sync-tables"
      run_as:
        service_principal_name: "sp-data-access"  # SP-Data
      tasks:
        - task_key: "create_synced_tables"
          # ... configuración de tareas
```

### Nota sobre el rol "Service Principal User"

> *"Users with the service principal manager role do not inherit the service principal user role. If you want to use the service principal to execute jobs, you need to explicitly assign yourself the service principal user role, even after creating the service principal."*
> — Documentación oficial de Databricks

Es decir, SP-Lakebase necesita **explícitamente** el rol "Service Principal User" sobre SP-Data para poder configurar el Run As.

### Permisos requeridos para crear Synced Tables

Según la documentación oficial:
> *"Create synced table: Requires Unity Catalog permissions to read the source table, write to the destination schema, and write to the pipeline storage schema."*

**Referencia:** [Access control lists](https://docs.databricks.com/aws/en/security/auth/access-control/)

---

## 5. Análisis: Vector Search vs Lakebase (pgvector)

### Recomendación: Lakebase con pgvector es la opción clara

### Tabla comparativa para ESTE caso de uso

| Criterio | Vector Search | Lakebase (pgvector) | Veredicto |
|----------|--------------|---------------------|-----------|
| **Escala** | Diseñado para 50M–1B vectores | Óptimo para <100M vectores | 40K productos → **Lakebase** |
| **Patrón de consulta** | Filtros + similaridad | SQL completo + JOINs + transacciones + similaridad | Filtro por distribuidor + lógica → **Lakebase** |
| **Coste** | Always-on (no scale-to-zero) | Scale-to-zero disponible | **Lakebase** |
| **Latencia** | 10–500ms | 20–50ms | **Lakebase** (ligeramente mejor) |
| **Throughput** | 1K+ QPS | 1K+ QPS | Empate |
| **Arquitectura existente** | Servicio adicional nuevo | Ya desplegado | **Lakebase** (sin cambios) |
| **Embeddings** | Delta Sync auto-embeds | Bring your own | VS tiene ventaja, pero aceptable |
| **Hybrid search + reranking** | Built-in (RRF) | Manual (construir en PLpgSQL) | VS tiene ventaja |
| **RLS (Row Level Security)** | No (roadmap) | Sí (nativo Postgres) | **Lakebase** |

### ¿Por qué Lakebase gana?

Según la Product Routing Guide oficial de Databricks:

> *"Lakebase (pgvector) is better when you need full SQL alongside similarity (JOINs, transactions), scale-to-zero, you're bringing your own embeddings"*

El caso del cliente encaja perfectamente:
1. **40K productos es trivial** para pgvector con HNSW
2. **SQL + similaridad:** filtrar por distribuidor, JOINs con precios/stock, lógica de negocio en funciones
3. **Ya desplegado:** solo `CREATE EXTENSION vector` + índice HNSW
4. **Coste:** no pagan endpoint always-on para dataset pequeño
5. **Una sola infraestructura:** búsqueda + recomendaciones + serving

### ¿Cuándo considerar Vector Search en el futuro?

- Si el catálogo crece a **>10M productos**
- Si necesitan **generación automática de embeddings** (Delta Sync auto-embed)
- Si quieren **hybrid search + reranking out-of-the-box** sin construirlo
- Si integran un **agente de IA** con VectorSearchRetrieverTool
- Si necesitan **búsqueda sobre documentos no estructurados** (PDFs, descripciones largas) a gran escala

### Patrón combinado (futuro avanzado)

Para catálogos muy grandes, existe un patrón híbrido documentado:
- **Vector Search:** retrieval sobre catálogos masivos (>10M)
- **Lakebase:** señales en tiempo real, estado, transacciones, serving final
- Referencia: "Building Real-Time Product Search with Databricks (Apr 2026)"

---

## 6. Arquitectura Detallada y Flujo de Datos

### Diagrama de Arquitectura Completo

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        DATABRICKS LAKEHOUSE                                  │
│                                                                              │
│  ┌──────────────┐     ┌──────────────────┐     ┌─────────────────────────┐ │
│  │ Distributor  │     │  Pipeline        │     │  Embedding Generation   │ │
│  │ Data Sources │────▶│  Medallion       │────▶│  (ai_query / Model      │ │
│  │ (APIs/feeds) │     │  Bronze→Silver→  │     │   Serving endpoint)     │ │
│  └──────────────┘     │  Gold            │     └───────────┬─────────────┘ │
│                       └──────────────────┘                 │               │
│                                                            ▼               │
│                       ┌──────────────────────────────────────────┐         │
│                       │  Gold Delta Table (Unity Catalog)         │         │
│                       │  catalog.schema.products_gold             │         │
│                       │  ┌──────┬────────┬──────┬───────┬──────┐ │         │
│                       │  │prod_ │distri_ │name  │descr_ │embed_│ │         │
│                       │  │id(PK)│butor_id│      │tion   │ding  │ │         │
│                       │  │INT   │INT     │TEXT  │TEXT   │ARRAY │ │         │
│                       │  │      │        │      │       │FLOAT │ │         │
│                       │  └──────┴────────┴──────┴───────┴──────┘ │         │
│                       └──────────────────┬───────────────────────┘         │
│                                          │                                 │
│                                          ▼                                 │
│                       ┌──────────────────────────────────────────┐         │
│                       │  Synced Table Pipeline (Lakeflow/DLT)    │         │
│                       │  Mode: TRIGGERED (incremental)           │         │
│                       │  Run As: SP-Data                         │         │
│                       │  Fires on: Delta table update            │         │
│                       │  Throughput: ~1,200 rows/sec/CU          │         │
│                       └──────────────────┬───────────────────────┘         │
│                                          │                                 │
└──────────────────────────────────────────┼─────────────────────────────────┘
                                           │
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                    LAKEBASE AUTOSCALING (PostgreSQL 17)                       │
│                    Proyecto: ecommerce-search | Branch: production            │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │  Synced Table: products (READ-ONLY)                                     ││
│  │                                                                         ││
│  │  Indexes:                                                               ││
│  │  ├── HNSW (embedding vector_cosine_ops) → búsqueda vectorial           ││
│  │  ├── B-tree (distributor_id) → filtrado rápido por distribuidor         ││
│  │  ├── GIN (search_vector tsvector) → full-text search                    ││
│  │  └── B-tree (category, price) → filtros adicionales                     ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │  Extensiones:                                                           ││
│  │  ├── vector (pgvector) → tipos y operadores vectoriales                 ││
│  │  ├── databricks_auth → autenticación OAuth                              ││
│  │  └── pg_stat_statements → monitorización de queries                     ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │  Funciones SQL/PLpgSQL (Capa de Serving):                               ││
│  │  ├── search_products_semantic(embedding, distributor_id, limit)          ││
│  │  ├── search_products_hybrid(text, embedding, distributor_id, limit)      ││
│  │  ├── recommend_similar_products(product_id, distributor_id, limit)       ││
│  │  └── get_product_details(product_id, distributor_id)                     ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │  Roles y Permisos:                                                      ││
│  │  ├── sp-ecommerce-backend (OAuth, SELECT + EXECUTE, read-only)          ││
│  │  ├── sp-admin (OAuth, ALL, admin)                                       ││
│  │  └── Default privileges configurados para futuros objetos               ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
│  Config: 1-2 CU Autoscaling | Scale-to-zero: OFF | Timeout: 300s           │
│  PITR: 7 días | Branch protection: production protegida                    │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   │ PostgreSQL wire protocol (port 5432)
                                   │ SSL/TLS required
                                   │ OAuth token (60-min rotation)
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                    BACKEND E-COMMERCE                                         │
│                                                                              │
│  ┌───────────────────┐    ┌─────────────────────────────────────────┐       │
│  │ Service Principal │    │ Embedding Service                        │       │
│  │ (Entra ID/OAuth)  │    │ (modelo local ONNX / Model Serving)     │       │
│  │ Client ID + Secret│    │ Genera embedding del query del usuario   │       │
│  └────────┬──────────┘    │ Latencia: ~10-20ms (local) / ~50ms (API)│       │
│           │               └──────────────────┬──────────────────────┘       │
│           ▼                                  │                              │
│  ┌────────────────────────────────────────────────────────────────┐         │
│  │ Connection Pool (psycopg3 + ConnectionPool)                    │         │
│  │ ├── min_size: 1 | max_size: 10                                │         │
│  │ ├── Token refresh: generate_database_credential() por conexión│         │
│  │ └── Connection retry logic (para cold start si aplica)        │         │
│  └────────────────────────────────┬───────────────────────────────┘         │
│                                   │                                         │
│  Flujo de una petición:           │                                         │
│  1. Frontend envía: query_text + distributor_id                             │
│  2. Backend genera query_embedding (embedding service local)                │
│  3. Backend llama función Lakebase via pool ◄──────────────────┘            │
│  4. Lakebase retorna resultados (~20-50ms)                                  │
│  5. Backend formatea y retorna al frontend                                  │
│                                                                              │
│  Latencia total estimada: 30-100ms end-to-end                               │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   │ HTTP/REST API
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                    FRONTEND E-COMMERCE                                        │
│                                                                              │
│  Usuario busca: "crema hidratante piel seca"                                │
│  → Resultados: productos relevantes ordenados por similaridad semántica     │
│  → Latencia percibida: < 200ms                                              │
│                                                                              │
│  Usuario ve producto → "Productos similares"                                │
│  → Recomendaciones basadas en embeddings del producto actual                │
│  → Latencia percibida: < 200ms                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Flujo Detallado: Ingesta y Preparación de Datos

```
FASE 1: Data Engineering (ya existente)
═══════════════════════════════════════

Distribuidores (APIs/CSVs/feeds)
        │
        ▼
┌─────────────────────┐
│  BRONZE             │ Raw data, formato original
│  (Landing zone)     │ Tabla: catalog.bronze.raw_products
└─────────┬───────────┘
          │ Limpieza, deduplicación, validación
          ▼
┌─────────────────────┐
│  SILVER             │ Datos limpios, tipados, con PK
│  (Cleaned)          │ Tabla: catalog.silver.products_clean
└─────────┬───────────┘
          │ Enriquecimiento, agregación, business logic
          ▼
┌─────────────────────┐
│  GOLD               │ Datos listos para consumo
│  (Business-ready)   │ Tabla: catalog.gold.products_serving
└─────────────────────┘


FASE 2: Embedding Generation (nuevo)
═════════════════════════════════════

Trigger: Cuando Gold table se actualiza (o scheduled)

┌─────────────────────────────────────────────────────────┐
│  Job/Pipeline de Embeddings                              │
│                                                          │
│  INPUT: catalog.gold.products_serving                    │
│                                                          │
│  PROCESO:                                                │
│  SELECT                                                  │
│    product_id,                                           │
│    distributor_id,                                       │
│    name,                                                 │
│    description,                                          │
│    category,                                             │
│    price,                                                │
│    stock,                                                │
│    ai_query(                                             │
│      'databricks-bge-large-en',                          │
│      CONCAT(name, ' | ', description, ' | ', category)   │
│    ) AS embedding                                        │
│  FROM catalog.gold.products_serving                      │
│  WHERE embedding IS NULL  -- solo nuevos/actualizados    │
│        OR updated_at > last_run_timestamp                │
│                                                          │
│  OUTPUT: catalog.gold.products_with_embeddings           │
│  (Tabla Delta con columna embedding ARRAY<FLOAT>)        │
└─────────────────────────────────────────────────────────┘


FASE 3: Sync to Lakebase (nuevo, via Synced Tables)
═══════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────┐
│  Synced Table Configuration                              │
│                                                          │
│  Source: catalog.gold.products_with_embeddings           │
│  Target: Lakebase PostgreSQL → schema.products           │
│  Mode: TRIGGERED                                         │
│  Primary Key: product_id                                 │
│                                                          │
│  Comportamiento:                                         │
│  - Se activa cuando la tabla Delta fuente cambia         │
│  - Aplica solo cambios incrementales (INSERT/UPDATE/DEL) │
│  - Para 40K productos: sync completo < 30 segundos       │
│  - Cambios incrementales: segundos                       │
│                                                          │
│  Pipeline DLT subyacente:                                │
│  - Gestionado automáticamente por Databricks             │
│  - Run As: SP-Data (con permisos UC)                     │
│  - Coste: solo cuando se ejecuta (triggered)             │
└─────────────────────────────────────────────────────────┘
```

### Flujo Detallado: Query en Tiempo Real

```
BÚSQUEDA SEMÁNTICA (Flujo completo de una petición)
═══════════════════════════════════════════════════

Tiempo total estimado: 30-100ms

┌──────┐  "crema hidratante"   ┌──────────┐
│ User │ ─────────────────────▶│ Frontend │
└──────┘                       └────┬─────┘
                                    │ POST /api/search
                                    │ {query: "crema hidratante", distributor_id: 42}
                                    ▼
                            ┌───────────────┐
                            │   Backend     │
                            │               │
                            │ Step 1: ──────┼──▶ Embedding Service (local/ONNX)
                            │ Generate      │    CONCAT("crema hidratante")
                            │ query         │    → vector(768) [0.12, -0.34, ...]
                            │ embedding     │◀── ~10-20ms
                            │ (~10-20ms)    │
                            │               │
                            │ Step 2: ──────┼──▶ Lakebase (via connection pool)
                            │ Call PG       │    SELECT * FROM
                            │ function      │    search_products_semantic(
                            │ (~20-50ms)    │      $embedding, 42, 20
                            │               │    );
                            │               │◀── [product_id, name, price, similarity]
                            │               │    20 rows, ordered by similarity
                            │               │
                            │ Step 3: ──────┼──▶ Format response
                            │ Return        │    JSON with products
                            │ (~1-2ms)      │
                            └───────┬───────┘
                                    │ 200 OK + JSON
                                    ▼
                            ┌───────────────┐
                            │   Frontend    │ Muestra resultados
                            └───────────────┘


RECOMENDACIÓN DE PRODUCTOS (Flujo)
══════════════════════════════════

Trigger: Usuario hace click en un producto

┌──────┐  click product_123     ┌──────────┐
│ User │ ─────────────────────▶│ Frontend │
└──────┘                       └────┬─────┘
                                    │ GET /api/recommendations
                                    │ {product_id: 123, distributor_id: 42}
                                    ▼
                            ┌───────────────┐
                            │   Backend     │
                            │               │
                            │ Step 1: ──────┼──▶ Lakebase (via connection pool)
                            │ Call PG       │    SELECT * FROM
                            │ function      │    recommend_similar_products(
                            │ (~20-50ms)    │      123, 42, 10
                            │               │    );
                            │               │◀── [product_id, name, price, similarity]
                            │               │    La función internamente:
                            │               │    1. Obtiene embedding del producto 123
                            │               │    2. Busca los 10 más similares
                            │               │    3. Excluye el producto original
                            │               │
                            │ Step 2: ──────┼──▶ Format response
                            │ Return        │
                            └───────┬───────┘
                                    │ 200 OK + JSON
                                    ▼
                            ┌───────────────┐
                            │   Frontend    │ "Productos similares"
                            └───────────────┘

Nota: Para recomendaciones NO se necesita generar embedding
del query porque ya existe en la tabla (es el embedding
del producto que el usuario está viendo).
```

### Funciones SQL Detalladas

#### Búsqueda Semántica

```sql
-- Extensión pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Crear índice HNSW para búsqueda vectorial rápida
-- m=16: número de conexiones por nodo (16 es buen default)
-- ef_construction=200: calidad del índice durante construcción
CREATE INDEX idx_products_embedding ON products
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 200);

-- Índice B-tree para filtrado rápido por distribuidor
CREATE INDEX idx_products_distributor ON products (distributor_id);

-- Índice GIN para full-text search
ALTER TABLE products ADD COLUMN search_vector tsvector
  GENERATED ALWAYS AS (
    to_tsvector('spanish', coalesce(name, '') || ' ' || coalesce(description, '') || ' ' || coalesce(category, ''))
  ) STORED;
CREATE INDEX idx_products_fts ON products USING gin (search_vector);

-- ═══════════════════════════════════════════════════════════════
-- FUNCIÓN: Búsqueda semántica (solo vectorial)
-- ═══════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION search_products_semantic(
    query_embedding vector(768),
    p_distributor_id INT,
    p_limit INT DEFAULT 20
) RETURNS TABLE (
    product_id INT,
    name TEXT,
    description TEXT,
    category TEXT,
    price NUMERIC,
    similarity FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.product_id,
        p.name,
        p.description,
        p.category,
        p.price,
        1 - (p.embedding <=> query_embedding) AS similarity
    FROM products p
    WHERE p.distributor_id = p_distributor_id
    ORDER BY p.embedding <=> query_embedding
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- ═══════════════════════════════════════════════════════════════
-- FUNCIÓN: Búsqueda híbrida (vectorial + full-text con RRF)
-- ═══════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION search_products_hybrid(
    query_text TEXT,
    query_embedding vector(768),
    p_distributor_id INT,
    p_limit INT DEFAULT 20,
    p_vector_weight FLOAT DEFAULT 0.7,
    p_text_weight FLOAT DEFAULT 0.3
) RETURNS TABLE (
    product_id INT,
    name TEXT,
    description TEXT,
    category TEXT,
    price NUMERIC,
    combined_score FLOAT
) AS $$
BEGIN
    RETURN QUERY
    WITH vector_results AS (
        SELECT
            p.product_id,
            ROW_NUMBER() OVER (ORDER BY p.embedding <=> query_embedding) AS vector_rank
        FROM products p
        WHERE p.distributor_id = p_distributor_id
        ORDER BY p.embedding <=> query_embedding
        LIMIT p_limit * 3
    ),
    text_results AS (
        SELECT
            p.product_id,
            ROW_NUMBER() OVER (ORDER BY ts_rank(p.search_vector, plainto_tsquery('spanish', query_text)) DESC) AS text_rank
        FROM products p
        WHERE p.distributor_id = p_distributor_id
          AND p.search_vector @@ plainto_tsquery('spanish', query_text)
        LIMIT p_limit * 3
    ),
    -- Reciprocal Rank Fusion (RRF)
    combined AS (
        SELECT
            COALESCE(v.product_id, t.product_id) AS product_id,
            (p_vector_weight * (1.0 / (60 + COALESCE(v.vector_rank, 1000)))) +
            (p_text_weight * (1.0 / (60 + COALESCE(t.text_rank, 1000)))) AS rrf_score
        FROM vector_results v
        FULL OUTER JOIN text_results t ON v.product_id = t.product_id
    )
    SELECT
        p.product_id,
        p.name,
        p.description,
        p.category,
        p.price,
        c.rrf_score AS combined_score
    FROM combined c
    JOIN products p ON p.product_id = c.product_id
    ORDER BY c.rrf_score DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- ═══════════════════════════════════════════════════════════════
-- FUNCIÓN: Recomendador de productos similares
-- (Migración desde CosmosDB)
-- ═══════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION recommend_similar_products(
    p_product_id INT,
    p_distributor_id INT,
    p_limit INT DEFAULT 10,
    p_same_category BOOLEAN DEFAULT FALSE
) RETURNS TABLE (
    product_id INT,
    name TEXT,
    category TEXT,
    price NUMERIC,
    similarity FLOAT
) AS $$
DECLARE
    source_embedding vector(768);
    source_category TEXT;
BEGIN
    -- Obtener embedding y categoría del producto fuente
    SELECT p.embedding, p.category
    INTO source_embedding, source_category
    FROM products p
    WHERE p.product_id = p_product_id
      AND p.distributor_id = p_distributor_id;

    -- Si no se encuentra el producto, retornar vacío
    IF source_embedding IS NULL THEN
        RETURN;
    END IF;

    -- Buscar productos más similares
    RETURN QUERY
    SELECT
        p.product_id,
        p.name,
        p.category,
        p.price,
        1 - (p.embedding <=> source_embedding) AS similarity
    FROM products p
    WHERE p.distributor_id = p_distributor_id
      AND p.product_id != p_product_id
      AND (NOT p_same_category OR p.category = source_category)
    ORDER BY p.embedding <=> source_embedding
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;
```

### Decisiones Arquitectónicas Clave

| # | Decisión | Justificación |
|---|----------|---------------|
| 1 | **Embeddings en batch (Lakehouse)** | Compute-intensive → más barato en batch. Synced tables los sincronizan automáticamente |
| 2 | **Query embedding en tiempo real (backend)** | Solo 1 vector por petición. Modelo local/ONNX (~10-20ms) o Model Serving (~50ms) |
| 3 | **Triggered mode (no continuous)** | Catálogo no cambia cada segundo. Near-real-time suficiente. Menor coste |
| 4 | **HNSW index (no IVFFlat)** | 40K productos → HNSW óptimo (mejor recall, baja latencia). IVFFlat para millones |
| 5 | **Pre-filtrado por distributor_id** | 40K → ~3K productos. Ahorro 93% en comparaciones vectoriales |
| 6 | **Scale-to-zero OFF en prod** | E-commerce = tráfico continuo. Cold start inaceptable. Coste ~$3,500-7,000/año |
| 7 | **Funciones PLpgSQL como API** | Encapsulación, versionado, reutilización. Minimiza lógica en backend |
| 8 | **search_vector GENERATED ALWAYS** | Full-text index se actualiza automáticamente con los datos |

### Consideraciones de Rendimiento

| Aspecto | Valor estimado | Nota |
|---------|---------------|------|
| Tamaño embedding (768 dims, float32) | ~3 KB/producto | |
| Total embeddings (40K productos) | ~120 MB | Cabe en 1 CU (2 GB RAM) |
| Total con datos + indices | ~300-500 MB | Cabe sobradamente en 1-2 CU |
| Latencia vector search (HNSW, 3K vectors) | ~5-20 ms | Pre-filtrado por distribuidor |
| Latencia hybrid search | ~20-50 ms | Vector + FTS + RRF |
| Latencia recomendación | ~10-30 ms | Lookup embedding + vector search |
| QPS soportados (1 CU) | ~1,000-5,000 | Depende de complejidad de función |

---

## 7. Migración desde CosmosDB: Plan y Consideraciones

### Viabilidad: ✅ Viable y recomendada

La migración consolida 4 sistemas (CosmosDB + ArgoCD + Kubernetes + API Python) en 1 (Lakebase + funciones SQL), manteniendo el mismo patrón de acceso (endpoint → función → resultado).

### Plan de Migración por Fases

```
FASE 1: Buscador en Lakebase (EN CURSO)
════════════════════════════════════════
- Synced tables con catálogo de productos
- Funciones de búsqueda SQL (search_products_semantic/hybrid)
- Service Principal + OAuth desde backend
- Validación de latencia y rendimiento
- Duración estimada: 4-6 semanas

FASE 2: Recomendador Simple (SIGUIENTE)
═══════════════════════════════════════
- Función recommend_similar_products()
- Misma infraestructura, mismos embeddings
- Migración progresiva: dual-write o shadow mode
  (consultar ambos y comparar resultados)
- Backend: switch de CosmosDB a Lakebase por endpoint
- Duración estimada: 2-4 semanas

FASE 3: Recomendadores Avanzados (MEDIO PLAZO)
══════════════════════════════════════════════
- Migrar lógica Python de ArgoCD a funciones PLpgSQL
- Collaborative filtering, trending, cross-sell
- Posiblemente: algunas funciones pueden quedarse como
  microservicios ligeros que consultan Lakebase
- Decommission CosmosDB + ArgoCD cluster
- Duración estimada: 6-8 semanas
```

### Beneficios esperados

| Beneficio | Detalle |
|-----------|---------|
| **Simplificación** | De 4 sistemas a 1. Un solo endpoint, un solo lenguaje (SQL) |
| **Coste** | Lakebase 1-2 CU ≈ $3,500-$7,000/año vs CosmosDB + K8s + ArgoCD |
| **Coherencia** | Datos siempre sincronizados via synced tables. No pipelines ad-hoc |
| **Operativa** | Un DAB en Git con CI/CD vs Terraform + Helm charts en paralelo |
| **Seguridad** | Un solo modelo de AuthN/AuthZ. Unity Catalog governance |

### Riesgos y Mitigaciones

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Synced tables read-only | No se puede escribir directamente | Toda la lógica de escritura va al Lakehouse (Delta). Lakebase solo sirve |
| PLpgSQL para lógica compleja | Mantenibilidad | Funciones modulares + tests. Considerar patrón híbrido (backend para orquestación, SQL para datos) |
| Sin readable secondaries (Autoscaling) | Sin HA de lectura | Para 40K productos y 1-2 CU, un solo compute es suficiente. Evaluar si crece |
| Rango autoscaling max-min ≤ 16 CU | Limitación de escalado | Para este volumen no aplica (1-2 CU) |
| Cold start si scale-to-zero activo | Latencia primera petición | Desactivar en producción |
| Embeddings desactualizados | Resultados stale | Triggered sync + embedding pipeline al actualizar catálogo |

### Limitaciones de Lakebase Autoscaling

- Máximo 16 TB storage por instancia (más que suficiente)
- Máximo 4,000 conexiones concurrentes (más que suficiente)
- Sin migración directa Provisioned ↔ Autoscaling (usar pg_dump/pg_restore)
- Compliance: soporta HIPAA, C5, TISAX (verificar si necesitan otro)
- Sin logical replication (no pueden replicar a otro PG)

---

## 8. Limitaciones y Buenas Prácticas

### Buenas prácticas operativas

1. **Connection pooling siempre:** psycopg3 ConnectionPool con min/max configurado
2. **Connection retry logic:** para manejar reconexiones y posibles cold starts
3. **Prepared statements con cuidado:** se pierden si hay reconexión (pool lo gestiona)
4. **REINDEX CONCURRENTLY:** programar si hay muchos updates en el catálogo
5. **VACUUM:** Lakebase ejecuta autovacuum automáticamente
6. **pg_stat_statements:** activar para monitorizar queries lentas
7. **Índices parciales:** considerar para optimizar si solo subconjuntos se consultan frecuentemente

### Buenas prácticas de seguridad

1. **Mínimo privilegio:** SP del backend solo SELECT + EXECUTE
2. **No exponer connection string:** usar variables de entorno / secrets
3. **Rotación de OAuth secrets:** configurar vida útil apropiada (no más de 180 días)
4. **Audit logging:** revisar pg_stat_activity para detectar anomalías
5. **Branch protection:** producción protegida (ya implementado)

### Buenas prácticas de rendimiento

1. **Pre-filtrar antes de vector search:** siempre `WHERE distributor_id = X` antes del `ORDER BY embedding <=>`
2. **Ajustar ef_search en runtime:** `SET hnsw.ef_search = 100;` (más alto = más recall, más lento)
3. **Limitar resultados:** siempre usar LIMIT
4. **Evitar SELECT *:** retornar solo columnas necesarias (no el embedding de 768 floats)
5. **Warm cache:** primera query tras deploy será más lenta (LFC cold)

---

## 9. Script de Presentación al Cliente

### APERTURA — Resumen Ejecutivo (2-3 min)

**Puntos de conversación:**

> "Hemos revisado en detalle todo el trabajo que habéis estado realizando con Lakebase Autoscaling y queremos transmitiros que el enfoque que estáis siguiendo es correcto y está muy bien planteado."

> "En resumen: Lakebase Autoscaling es la herramienta adecuada para vuestro caso de uso, el patrón de autenticación es el que recomendamos oficialmente, y la arquitectura con funciones SQL es totalmente válida. Además, hemos analizado si sería mejor usar Vector Search para el buscador y la conclusión es que para vuestro volumen y necesidades, pgvector en Lakebase es la opción óptima."

> "Vamos a ir punto por punto con nuestras recomendaciones específicas."

---

### BLOQUE 1 — Validación del caso de uso (3-5 min)

**Puntos de conversación:**

> "Lakebase está diseñado exactamente para este tipo de caso de uso. 'Serve lakehouse data at low latency' es uno de los casos de uso primarios documentados. Con vuestro volumen de 40.000 productos y ~3.000 por consulta, estáis en un rango donde Lakebase funciona de forma óptima."

> "Para daros un dato concreto: Lakebase está diseñado para soportar miles de point operations por segundo con latencias inferiores a 10ms. Vuestro caso encaja perfectamente."

> "Además, con la extensión pgvector que viene incluida, podéis hacer búsqueda semántica directamente en PostgreSQL, lo que os abre la puerta tanto al buscador como a los futuros recomendadores."

**Transición:** "Dicho esto, vamos a ver el tema del dimensionamiento, que es donde teníais más dudas..."

---

### BLOQUE 2 — Dimensionamiento (5-7 min)

**Puntos de conversación:**

> "Un punto importante que queríamos clarificar: en Lakebase Autoscaling, 1 CU equivale a aproximadamente 2 GB de RAM. Esto es diferente de Lakebase Provisioned donde 1 CU eran 16 GB. Es un cambio de escala que puede generar confusión."

> "Con 1 CU tenéis 209 conexiones concurrentes máximas y un rendimiento de entre 1.700 y 20.000 point-gets por segundo para filas de 1KB, dependiendo de si los datos caben en caché — que en vuestro caso sí cabrán."

> "Nuestra recomendación: subid a 1-2 CU en producción. Vuestro catálogo completo con embeddings ocupa unos 160-300 MB, que cabe sobradamente en 2 GB. Con 2 CU tenéis 419 conexiones disponibles, que os da margen para picos de tráfico del e-commerce."

> "Sobre el coste: estamos hablando de unos 3.500-7.000 dólares al año para la capa de serving de todo vuestro buscador y recomendador. Es muy competitivo comparado con CosmosDB + Kubernetes."

> "Una recomendación importante: desactivad scale-to-zero en producción. El cold start es de unos 500ms a 2 segundos, que para un e-commerce es inaceptable. En dev y pre, sí dejadlo activado para ahorrar."

> "En cuanto a métricas: las claves son QPS, latencia p95/p99, conexiones activas, y cache hit ratio. Os recomendamos activar pg_stat_statements para tener visibilidad."

**Transición:** "Sobre la autenticación del backend, que era otro de vuestros puntos..."

---

### BLOQUE 3 — Autenticación (3-5 min)

**Puntos de conversación:**

> "El patrón que habéis implementado — Service Principal con OAuth desde el backend — es exactamente el que recomendamos oficialmente. Hay documentación específica para esto: 'Connect external app to Lakebase using SDK'."

> "El flujo es: vuestro SP tiene un OAuth secret, el SDK genera un database credential que dura 60 minutos, y el connection pool se encarga de la rotación automática. Cada nueva conexión del pool obtiene un token fresco."

> "Lo que habéis hecho con databricks_auth y los roles granulares por schema nos parece correcto. El principio de mínimo privilegio aplicado al SP del backend — solo SELECT y EXECUTE — es exactamente lo que recomendamos."

**Transición:** "Ahora, sobre la duda que teníais con los permisos para crear synced tables..."

---

### BLOQUE 4 — Permisos para Synced Tables (3-5 min)

**Puntos de conversación:**

> "Entendemos el problema: el SP de Lakebase gestiona la infraestructura pero no tiene permisos sobre los esquemas de Unity Catalog."

> "De las dos opciones que planteáis, nuestra recomendación es la Opción B: usar Run As con un Service Principal dedicado que ya tenga los permisos de datos."

> "La razón principal es la separación de responsabilidades. El SP de Lakebase debe gestionar infraestructura; un SP de datos debe gestionar acceso a datos. Si un SP se compromete, el impacto está contenido."

> "La implementación es sencilla: el SP-Data necesita SELECT en las tablas fuente, USE CATALOG y USE SCHEMA, y CAN USE en el proyecto Lakebase. El SP-Lakebase necesita el rol 'Service Principal User' sobre SP-Data para poder configurar el Run As."

> "Un punto importante: el rol Service Principal Manager no hereda el rol Service Principal User. Hay que asignarlo explícitamente."

**Transición:** "Ahora, algo que creemos que os puede aportar mucho valor y que no estaba en las preguntas originales: hemos analizado si deberíais usar Vector Search o pgvector..."

---

### BLOQUE 5 — Vector Search vs pgvector (5-7 min)

**Puntos de conversación:**

> "Hemos analizado si para vuestro buscador semántico y los futuros recomendadores sería mejor usar Databricks Vector Search como servicio separado o pgvector directamente en Lakebase."

> "La conclusión es clara: para vuestro caso, Lakebase con pgvector es la opción correcta. Os explico por qué:"

> "Primero, escala: Vector Search está diseñado para datasets de 50 millones a mil millones de vectores. Vosotros tenéis 40.000 productos. Es como usar un camión de 18 ruedas para llevar una caja de pizza."

> "Segundo, patrón de consulta: vosotros necesitáis filtrar por distribuidor, hacer JOINs con tablas de precios y stock, aplicar lógica de negocio... todo eso junto con la similaridad vectorial. Eso es exactamente donde pgvector en Lakebase brilla: SQL completo junto con búsqueda vectorial."

> "Tercero, coste: Vector Search tiene un endpoint always-on que no escala a cero. Lakebase sí puede hacerlo. Para un dataset pequeño, pagaríais más por Vector Search."

> "Cuarto, ya lo tenéis desplegado: añadir pgvector es literalmente un CREATE EXTENSION vector y crear un índice. No es un servicio nuevo."

> "¿Cuándo consideraríais Vector Search? Si en el futuro vuestro catálogo crece a más de 10 millones de productos, o si necesitáis generación automática de embeddings con Delta Sync. Pero por ahora, pgvector es el camino."

**Transición:** "Os vamos a mostrar cómo quedaría la arquitectura completa..."

---

### BLOQUE 6 — Arquitectura y Flujo de Datos (7-10 min)

**Puntos de conversación:**

> "La arquitectura tiene 6 capas. Vosotros ya tenéis las primeras capas del pipeline de datos. Lo que añadimos es la generación de embeddings, el sync, y las funciones de serving."

[Presentar diagrama de arquitectura]

> "El flujo es: vuestro pipeline medallion prepara los datos como ya lo hace. Añadimos un step de generación de embeddings usando ai_query con un modelo como BGE-large. Esto se ejecuta en batch, cada vez que se actualiza el catálogo."

> "Los embeddings se almacenan como columna en la tabla Gold de Delta. Luego, las synced tables en modo triggered sincronizan automáticamente todo a Lakebase, incluyendo los embeddings."

> "En Lakebase creáis un índice HNSW sobre la columna de embeddings — esto es lo que permite búsquedas vectoriales en milisegundos — y vuestras funciones SQL combinan el filtro por distribuidor con la similaridad vectorial."

> "Una decisión importante: los embeddings del catálogo se generan en batch, pero el embedding del query del usuario se genera en tiempo real. Para eso, os recomendamos tener un modelo ligero en el backend — puede ser ONNX Runtime — que añade solo 10-20ms."

> "El pre-filtrado por distributor_id es crítico: reducís las comparaciones vectoriales de 40.000 a ~3.000, un ahorro del 93%. PostgreSQL maneja esto eficientemente con el índice B-tree."

**Transición:** "Con esta arquitectura, la migración desde CosmosDB se simplifica enormemente..."

---

### BLOQUE 7 — Migración desde CosmosDB (5-7 min)

**Puntos de conversación:**

> "La migración desde CosmosDB tiene todo el sentido. Estáis pasando de 4 sistemas — CosmosDB, Kubernetes, ArgoCD, API Python — a uno solo: Lakebase con funciones SQL."

> "Os proponemos hacerlo en tres fases. Fase 1: el buscador, que es lo que estáis haciendo ahora. Fase 2: el recomendador simple — que literalmente usa la misma infraestructura y los mismos embeddings, solo necesitáis una función más. Fase 3: los recomendadores avanzados, donde migráis la lógica Python a PLpgSQL."

> "Un punto sobre la Fase 3: no toda la lógica tiene que ir a PLpgSQL. Si hay lógica de orquestación muy compleja, puede quedarse en el backend. Lo que sí debe estar en Lakebase es el acceso a datos y la búsqueda vectorial."

> "En cuanto a riesgos: las synced tables son read-only, así que toda la escritura sigue yendo al Lakehouse. Y PLpgSQL puede ser difícil de mantener si la lógica es muy compleja — recomendamos funciones modulares y tests automatizados."

**Transición:** "Para terminar, os dejamos algunas limitaciones y buenas prácticas importantes..."

---

### BLOQUE 8 — Limitaciones y Buenas Prácticas (3-5 min)

**Puntos de conversación:**

> "Algunas cosas importantes a tener en cuenta:"

> "Connection retry logic en el backend: aunque tengáis scale-to-zero desactivado, siempre puede haber reconexiones. El pool debería manejar reintentos automáticos."

> "No retornéis el embedding en las respuestas: son 768 floats que el frontend no necesita. Solo retornad las columnas útiles."

> "Sobre índices: HNSW se reconstruye incrementalmente, pero si hacéis muchos updates masivos, programad un REINDEX CONCURRENTLY periódico."

> "Monitorizad con pg_stat_statements: os dará visibilidad sobre qué queries son lentas y dónde podéis optimizar."

> "Y un tip de rendimiento: ajustad ef_search en runtime. Podéis hacer SET hnsw.ef_search = 100 para más recall o bajarlo a 40 para más velocidad."

---

### CIERRE — Próximos Pasos (2-3 min)

**Puntos de conversación:**

> "En resumen, nuestras recomendaciones concretas son:"

> "1. Subid a 1-2 CU en producción y desactivad scale-to-zero."
> "2. Implementad la Opción B para los permisos de synced tables."
> "3. Añadid pgvector con un índice HNSW — esto os habilita tanto el buscador como los recomendadores."
> "4. Desarrollad las funciones de búsqueda semántica empezando por la función básica."
> "5. Haced un POC del buscador con embeddings reales de vuestro catálogo."
> "6. Una vez validado, planificad la migración de recomendadores desde CosmosDB."

> "Estáis en el camino correcto. El trabajo que habéis hecho con el DAB, los entornos, los roles y la automatización es muy sólido. Las piezas que faltan — embeddings, pgvector, funciones — son relativamente sencillas de añadir sobre lo que ya tenéis."

> "Contad con nosotros para cualquier duda durante la implementación."

---

## Referencias

- [What is Lakebase Autoscaling?](https://docs.databricks.com/aws/en/oltp/projects/about)
- [Manage computes (sizing)](https://docs.databricks.com/aws/en/oltp/projects/manage-computes)
- [Scale to zero](https://docs.databricks.com/aws/en/oltp/projects/scale-to-zero)
- [Connect external app to Lakebase using SDK](https://docs.databricks.com/aws/en/oltp/projects/external-apps-connect)
- [Access control lists (permissions)](https://docs.databricks.com/aws/en/security/auth/access-control/)
- [Manage project permissions](https://docs.databricks.com/aws/en/oltp/projects/manage-project-permissions)
- [Manage identities for Lakeflow Jobs (Run As)](https://docs.databricks.com/aws/en/jobs/privileges)
- [Service principals](https://docs.databricks.com/aws/en/admin/users-groups/service-principals)
- [Lakebase Autoscaling limitations](https://docs.databricks.com/aws/en/oltp/projects/limitations)
- [How to perform Semantic Search in Databricks Lakebase (Community Blog)](https://community.databricks.com/t5/technical-blog/how-to-perform-semantic-search-in-databricks-lakebase/ba-p/139846)
- [AI Functions (ai_query)](https://docs.databricks.com/aws/en/large-language-models/ai-functions)
- [Declarative Automation Bundles](https://docs.databricks.com/aws/en/dev-tools/bundles)
