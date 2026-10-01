import os
import json
import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from config.constants import (
    RESULT_INVENTARIO, 
    RESULT_REPORT_FILE, 
    ANALIZAR_BD_FILE, 
    DESCARGA_TABLAS_FILE
)
from utils.ghe_client import resolver_repositorio, obtener_arbol_archivos, obtener_contenidos_batch_graphql
from utils.db_extractor import extraer_tablas_estrictas
from utils.file_extractor import extraer_fuente_completa_por_indice
from utils.descarga_enricher import enriquecer_con_descarga_tablas


def procesar_fuente_individual(item):
    resource = item.get("resource")
    tipo_fuente = item.get("tipo_fuente_entrada")
    total_sources = item.get("total_sources_componente", 1)
    idx_source = item.get("indice_source", 1)
    es_bd = item.get("es_base_datos", "NO")

    registro = {
        "Resource / Job": resource,
        "UA": item.get("ua"),
        "Versión PRO": item.get("version_pro"),
        "Total Fuentes Job": total_sources,
        "Fuente Nro": idx_source,
        "Tipo Fuente Entrada": tipo_fuente,
        "Objeto / Tabla / Archivo Identificado": "N/A",
        "Service Name": "N/A",
        "Estado": "PROCESADO"
    }

    try:
        repo_info = resolver_repositorio(resource)
        if repo_info:
            owner, repo, branch = repo_info["owner"], repo_info["repo"], repo_info["branch"]
            archivos = obtener_arbol_archivos(owner, repo, branch)
            archivos_interes = [f['path'] for f in archivos if f['path'].endswith((".java", ".sql")) and "src/test/" not in f['path']]

            if archivos_interes:
                contenidos = obtener_contenidos_batch_graphql(owner, repo, branch, archivos_interes)
                datos_fuente = extraer_fuente_completa_por_indice(contenidos, idx_source)

                if datos_fuente.get("service_name") and datos_fuente["service_name"] != "N/A":
                    registro["Service Name"] = datos_fuente["service_name"]

                if es_bd == "NO":
                    arch = datos_fuente.get("archivo", "")
                    registro["Objeto / Tabla / Archivo Identificado"] = arch if arch else f"ARCHIVO_{tipo_fuente.split('.')[-1].upper()}"
                    registro["Estado"] = "OK" if arch else "FORMATO_GENERICO"
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
    print("🚀 FASE 2 PARALELA: Extrayendo identificadores/tablas con hilos múltiples...\n", flush=True)

    if not os.path.exists(ruta_json_fase1):
        print(f"⚠️ El archivo '{ruta_json_fase1}' no existe.", flush=True)
        return

    with open(ruta_json_fase1, 'r', encoding='utf-8') as f:
        data_json = json.load(f)

    todas_las_fuentes = data_json.get("data", [])
    total = len(todas_las_fuentes)
    resultados = []

    MAX_WORKERS = 15
    print(f"⚡ Ejecutando con {MAX_WORKERS} hilos concurrentes para {total} registros...", flush=True)

    inicio_tiempo = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(procesar_fuente_individual, item): item for item in todas_las_fuentes}
        completados = 0
        for future in as_completed(futures):
            completados += 1
            resultados.append(future.result())

            if completados % 50 == 0 or completados == total:
                print(f"  [PROGRESO] {completados}/{total} fuentes procesadas...", flush=True)

    tiempo_total = round(time.time() - inicio_tiempo, 2)

    resultados.sort(key=lambda x: (x["Resource / Job"], x["Fuente Nro"]))

    # PASO INTERMEDIO: Cruzar y reemplazar con DESCARGA DE TABLAS LRBA.xlsx
    print("🔄 Aplicando paso intermedio de depuración desde 'DESCARGA DE TABLAS LRBA.xlsx'...", flush=True)
    resultados = enriquecer_con_descarga_tablas(resultados, DESCARGA_TABLAS_FILE)

    if os.path.dirname(ruta_excel_salida):
        os.makedirs(os.path.dirname(ruta_excel_salida), exist_ok=True)

    df = pd.DataFrame(resultados)
    df.to_excel(ruta_excel_salida, index=False, sheet_name="Inventario_Fuentes_Completo")

    if os.path.dirname(RESULT_INVENTARIO):
        os.makedirs(os.path.dirname(RESULT_INVENTARIO), exist_ok=True)

    with open(RESULT_INVENTARIO, "w", encoding="utf-8") as f:
        json.dump({"data": resultados}, f, indent=4)

    print(f"\n✅ PROCESO FINALIZADO EN {tiempo_total} SEGUNDOS:")
    print(f"  - Total fuentes clasificadas y cruzadas: {len(resultados)}")
    print(f"  - Reporte Excel final guardado en: '{ruta_excel_salida}'")


def initialize():
    ejecutar_fase_2(ANALIZAR_BD_FILE, RESULT_REPORT_FILE)


if __name__ == "__main__":
    initialize()