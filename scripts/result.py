import os
import json
import time
import urllib3
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from config.constants import (
    GHE_DOMAIN, 
    GHE_TOKEN, 
    RESULT_INVENTARIO, 
    RESULT_REPORT_FILE, 
    ORGANIZACIONES_CONOCIDAS, 
    ANALIZAR_BD_FILE
)
from utils.extractor import (
    extraer_tablas_estrictas, 
    extraer_archivo_especifico_por_indice
)

# Silenciar advertencias de SSL corporativo
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuración global de sesión HTTP con reintentos
session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {GHE_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
})
session.verify = False

retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))

# Diccionarios de caché local para evitar consultas repetidas al mismo repositorio
CACHE_REPOS = {}
CACHE_CONTENIDOS = {}


def resolver_repositorio(resource_name):
    """Obtiene información del repo usando caché local para no repetir peticiones."""
    repo_slug = resource_name.lower()
    
    if repo_slug in CACHE_REPOS:
        return CACHE_REPOS[repo_slug]

    for org in ORGANIZACIONES_CONOCIDAS:
        try:
            url_directa = f"https://{GHE_DOMAIN}/api/v3/repos/{org}/{repo_slug}"
            resp = session.get(url_directa, timeout=8)
            if resp.status_code == 200:
                datos = resp.json()
                resultado = {
                    "owner": org,
                    "repo": repo_slug,
                    "branch": datos.get("default_branch", "master")
                }
                CACHE_REPOS[repo_slug] = resultado
                return resultado
        except Exception:
            pass
            
    CACHE_REPOS[repo_slug] = None
    return None


def obtener_arbol_archivos(owner, repo, branch):
    try:
        url = f"https://{GHE_DOMAIN}/api/v3/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        resp = session.get(url, timeout=8)
        if resp.status_code == 200:
            return resp.json().get("tree", [])
    except Exception:
        pass
    return []


def obtener_contenidos_batch_graphql(owner, repo, branch, paths):
    if not paths:
        return {}
    
    cache_key = f"{owner}/{repo}@{branch}"
    if cache_key in CACHE_CONTENIDOS:
        return CACHE_CONTENIDOS[cache_key]

    url_graphql = f"https://{GHE_DOMAIN}/api/graphql"
    queries = []
    for idx, path in enumerate(paths[:30]):
        queries.append(f'file_{idx}: object(expression: "{branch}:{path}") {{ ... on Blob {{ text }} }}')
    
    query_body = f'query {{ repository(owner: "{owner}", name: "{repo}") {{ {" ".join(queries)} }} }}'
    contenidos = {}
    
    try:
        resp = session.post(url_graphql, json={"query": query_body}, timeout=12)
        if resp.status_code == 200:
            data = resp.json().get("data", {}).get("repository", {}) or {}
            for idx, path in enumerate(paths[:30]):
                blob = data.get(f"file_{idx}")
                if blob and "text" in blob and blob["text"]:
                    contenidos[path] = blob["text"]
    except Exception:
        pass

    CACHE_CONTENIDOS[cache_key] = contenidos
    return contenidos


def procesar_fuente_individual(item):
    """Procesa una única fuente de entrada (ejecutado concurrentemente por los hilos)."""
    resource = item.get("resource")
    ua = item.get("ua")
    version_pro = item.get("version_pro")
    tipo_fuente = item.get("tipo_fuente_entrada")
    total_sources = item.get("total_sources_componente", 1)
    idx_source = item.get("indice_source", 1)
    es_bd = item.get("es_base_datos", "NO")

    registro = {
        "Resource / Job": resource,
        "UA": ua,
        "Versión PRO": version_pro,
        "Total Sources Job": total_sources,
        "Fuente Nro": idx_source,
        "Tipo Fuente Entrada": tipo_fuente,
        "Objeto / Tabla / Archivo Identificado": "N/A",
        "Estado": "PROCESADO"
    }

    try:
        repo_info = resolver_repositorio(resource)

        if repo_info:
            owner, repo, branch = repo_info["owner"], repo_info["repo"], repo_info["branch"]
            archivos = obtener_arbol_archivos(owner, repo, branch)

            archivos_interes = [
                f['path'] for f in archivos 
                if (f['path'].endswith(".java") or f['path'].endswith(".sql")) 
                and "src/test/" not in f['path']
            ]

            if archivos_interes:
                contenidos = obtener_contenidos_batch_graphql(owner, repo, branch, archivos_interes)

                # 1. BÚSQUEDA DE ARCHIVOS (Parquet, CSV, etc.)
                if es_bd == "NO":
                    arch_limpio = extraer_archivo_especifico_por_indice(contenidos, idx_source)
                    if arch_limpio:
                        registro["Objeto / Tabla / Archivo Identificado"] = arch_limpio
                        registro["Estado"] = "OK"
                    else:
                        nombre_formato = tipo_fuente.split(".")[-1].upper() if "." in tipo_fuente else tipo_fuente
                        registro["Objeto / Tabla / Archivo Identificado"] = f"ARCHIVO_{nombre_formato}"

                # 2. BÚSQUEDA DE BASE DE DATOS (JDBC)
                else:
                    tablas = extraer_tablas_estrictas(contenidos)
                    registro["Objeto / Tabla / Archivo Identificado"] = ", ".join(tablas) if tablas else "REQUIERE_REVISION_MANUAL"
                    registro["Estado"] = "OK" if tablas else "SIN_TABLAS_DETERMINADAS"
        else:
            registro["Estado"] = "REPO_NO_ENCONTRADO"

    except Exception as e:
        registro["Estado"] = f"ERROR: {str(e)}"

    return registro


def ejecutar_fase_2(ruta_json_fase1, ruta_excel_salida):
    print(f"🚀 FASE 2 PARALELA: Extrayendo identificadores/tablas con hilos múltiples...\n", flush=True)

    if not os.path.exists(ruta_json_fase1):
        print(f"⚠️ El archivo '{ruta_json_fase1}' no existe.", flush=True)
        return

    with open(ruta_json_fase1, 'r', encoding='utf-8') as f:
        data_json = json.load(f)

    todas_las_fuentes = data_json.get("data", [])
    total = len(todas_las_fuentes)
    resultados_finales = []

    # Configuración de concurrencia (12 hilos concurrentes)
    MAX_WORKERS = 15
    print(f"⚡ Ejecutando con {MAX_WORKERS} hilos concurrentes para {total} registros...", flush=True)

    inicio_tiempo = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(procesar_fuente_individual, item): item for item in todas_las_fuentes}
        
        completados = 0
        for future in as_completed(futures):
            completados += 1
            res = future.result()
            resultados_finales.append(res)

            # Notificación de progreso cada 50 elementos
            if completados % 50 == 0 or completados == total:
                print(f"  [PROGRESO] {completados}/{total} fuentes procesadas...", flush=True)

    tiempo_total = round(time.time() - inicio_tiempo, 2)

    # Ordenar los resultados para mantener la coherencia del JSON original
    resultados_finales.sort(key=lambda x: (x["Resource / Job"], x["Fuente Nro"]))

    # Exportar Excel Final
    directorio_salida = os.path.dirname(ruta_excel_salida)
    if directorio_salida:
        os.makedirs(directorio_salida, exist_ok=True)

    df = pd.DataFrame(resultados_finales)
    df.to_excel(ruta_excel_salida, index=False, sheet_name="Inventario_Fuentes_Completo")

    dir_inventario = os.path.dirname(RESULT_INVENTARIO)
    if dir_inventario:
        os.makedirs(dir_inventario, exist_ok=True)

    with open(RESULT_INVENTARIO, "w", encoding="utf-8") as f:
        json.dump({"data": resultados_finales}, f, indent=4)

    print(f"\n✅ PROCESO FINALIZADO EN {tiempo_total} SEGUNDOS:", flush=True)
    print(f"  - Total fuentes clasificadas: {len(resultados_finales)}", flush=True)
    print(f"  - Reporte Excel final guardado en: '{ruta_excel_salida}'", flush=True)


def initialize():
    ejecutar_fase_2(ANALIZAR_BD_FILE, RESULT_REPORT_FILE)


if __name__ == "__main__":
    initialize()