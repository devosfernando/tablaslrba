# Herramienta de Extracción y Análisis de Componentes GHE / DB2

Este proyecto consiste en un pipeline de scripts en Python diseñado para consultar, auditar y analizar componentes desplegados en producción desde GitHub Enterprise (GHE) y APIs corporativas. El objetivo principal es identificar aquellos componentes que interactúan con bases de datos (DB2/JDBC) y extraer de forma estricta las tablas involucradas mediante parsing de código fuente.


## 🚀 Descripción General

El proyecto está estructurado en tres fases secuenciales:

1. **Fase 0 - Extracción (`request.py`):** Realiza peticiones paginadas a la API del entorno para filtrar componentes activos desplegados en **PRO (Producción)** para un conjunto de UAs especificadas.

2. **Fase 1 - Identificación de BD (`analizar.py`):** Escanea los repositorios en GHE para localizar clases de tipo `Builder.java`, determinando si tienen integración con JDBC/Spark (`Source.Jdbc`) y clasificando el tipo de conector.

3. **Fase 2 - Parsing Estricto de Tablas (`result.py`):** Analiza exhaustivamente el código fuente (`.java`, `.sql`) de los jobs de tipo `Source.Jdbc.NativeQuery` utilizando expresiones regulares avanzadas y GraphQL para extraer los nombres físicos de las tablas de base de datos (DB2).


---

## 📁 Estructura del Proyecto

```text
.
├── config/
│   └── constants.py         # Constantes, tokens, regexes y configuraciones globales
├── request.py               # Extracción e inventario inicial de componentes PRO
├── analizar.py              # Fase 1: Filtro de repositorios y conectores JDBC
├── result.py                # Fase 2: Extracción estricta de tablas DB2 (NativeQuery)
└── README.md                # Documentación del proyecto
```

---

## 📋 Requisitos Previos

- **Python 3.8+**
- Librerías necesarias:
  ```bash
  pip install requests pandas openpyxl urllib3
  ```

---

## ⚙️ Configuración

Antes de ejecutar los scripts, asegúrate de configurar las variables de entorno o constantes dentro del módulo `config/constants.py` y `.env`:

- `GHE_TOKEN`: Token de acceso personal con permisos para consultar la API de GHE. (OBLIGATORIO)(debe ser declarados y generados en el archivo .env que debemos generar manualmente en la raiz del proyecto)`.env`

- `COOKIE_AUTH`: Cookie de acceso en lrba, se e ncuentra en cualquier header de petición en la consola de LRBA. (OBLIGATORIO) (debe ser declarados y generados en el archivo .env que debemos generar manualmente en la raiz del proyecto)`.env`

- `GHE_DOMAIN`: Dominio de tu instancia de GitHub Enterprise. (OPCIONAL) `config/constants.py`

- `ORGANIZACIONES_CONOCIDAS`: Lista de organizaciones en GHE donde se buscarán los repositorios. (OPCIONAL)
- `LISTA_UAS`: Lista de Acrónimos de Unidades de Aplicación a auditar. (OPCIONAL) `config/constants.py`

---

## 💻 Uso y Ejecución

### 0. Instala las dependencias necesarias.
```bash
pip install -r requirements.txt
```

Los módulos están diseñados para ejecutarse en secuencia:

### 1. Extracción de Componentes en Producción
```bash
python -c "import request; request.initialize()"
```
*Genera el archivo base de componentes.*

### 2. Identificación de Conexiones a Base de Datos
```bash
python -c "import analizar; analizar.initialize()"
```
*Filtra componentes con clases `Builder.java` que hacen uso de conectores JDBC.*

### 3. Extracción de Tablas Físicas DB2
```bash
python result.py
```
*Procesa únicamente los jobs `Source.Jdbc.NativeQuery` y genera un reporte Excel final con el inventario de tablas.*

---

## 🔍 Detalle de Módulos

### 📄 `request.py`
- Consume endpoints REST paginados (hasta 500 registros por página).
- Filtra componentes por parámetros como `uaAcronym`, `techSpecs` y entorno activo en Colombia (`COL`).
- Almacena el resultado inicial depurado en un archivo JSON.

### 📄 `analizar.py`
- Utiliza la API de Git Trees y GraphQL de GHE en lotes (*batch*) para acelerar las descargas de archivos.
- Escanea clases Java de patrón `*Builder.java` evitando rutas de prueba (`src/test/`).
- Clasifica el tipo de conector JDBC (`Source.Jdbc.NativeQuery`, `Source.Jdbc.Basic`, etc.).

### 📄 `result.py`
- Implementa filtros estrictos y expresiones regulares para limpiar comentarios y extraer palabras clave de consultas SQL (`FROM`, `JOIN`, sintaxis de esquemas `{SCHEMA}.TABLA`).
- Excluye falsos positivos como nombres de columnas, variables o palabras reservadas.
- Consolida y exporta los resultados finales a archivos JSON y hojas de cálculo de Excel (`.xlsx`).


## 📄 `main.py`
Archivo principal de jecución: python main.py