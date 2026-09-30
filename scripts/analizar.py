import json
import re
import os
import time
import requests
import pandas as pd
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import urllib3
from config.constants import (
    GHE_DOMAIN, 
    GHE_TOKEN, 
    ORGANIZACIONES_CONOCIDAS, 
    ANALIZAR_BD_FILE, 
    REQUEST_RESULT_FILE, 
    ANALIZAR_RESULT_FILE
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {GHE_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
})
session.verify = False

retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))


def resolver_repositorio(resource_name):
    repo_slug = resource_name.lower()
    for org in ORGANIZACIONES_CONOCIDAS:
        try:
            url_directa = f"https://{GHE_DOMAIN}/api/v3/repos/{org}/{repo_slug}"
            resp = session.get(url_directa, timeout=8)
            if resp.status_code == 200:
                datos = resp.json()
                return {
                    "owner": org,
                    "repo": repo_slug,
                    "branch": datos.get("default_branch", "master")
                }
        except Exception:
            pass
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
    url_graphql = f"https://{GHE_DOMAIN}/api/graphql"
    queries = []
    for idx, path in enumerate(paths[:15]):
        queries.append(f'file_{idx}: object(expression: "{branch}:{path}") {{ ... on Blob {{ text }} }}')
    
    query_body = f'query {{ repository(owner: "{owner}", name: "{repo}") {{ {" ".join(queries)} }} }}'
    contenidos = {}
    try:
        resp = session.post(url_graphql, json={"query": query_body}, timeout=12)
        if resp.status_code == 200:
            data = resp.json().get("data", {}).get("repository", {}) or {}
            for idx, path in enumerate(paths[:15]):
                blob = data.get(f"file_{idx}")
                if blob and "text" in blob and blob["text"]:
                    contenidos[path] = blob["text"]
    except Exception:
        pass
    return contenidos


def extrae_fuentes_de_builder(codigo_builder):
    """
    Identifica todos los tipos de fuentes declarados en Builder.java
    (Source.Jdbc, Source.Parquet, Source.Csv, etc.)
    """
    sources_encontrados = []
    pattern_sources = re.findall(r'Source\.\w+(?:\.\w+)?', codigo_builder)
    
    if pattern_sources:
        for src in pattern_sources:
            sources_encontrados.append(src)
    else:
        matches = re.findall(r'\.addSource\(([^)]+)\)', codigo_builder)
        for match in matches:
            clean_match = match.strip().split(',')[0]
            sources_encontrados.append(clean_match)

    return sources_encontrados


def ejecutar_fase_1(ruta_json_entrada, ruta_excel_salida):
    if not os.path.exists(ruta_json_entrada):
        print(f"❌ El archivo '{ruta_json_entrada}' no existe.")
        return

    with open(ruta_json_entrada, 'r', encoding='utf-8') as f:
        data_json = json.load(f)

    componentes = data_json.get("data", [])
    total = len(componentes)
    registros_desglosados = []

    print(f"🚀 FASE 1: Mapeando TODAS las fuentes de entrada ({total} componentes)...\n")

    for idx, item in enumerate(componentes, 1):
        resource = item.get("resource")
        ua = item.get("ua")
        version_pro = item.get("proVersion")

        print(f"[{idx}/{total}] 🔍 Escaneando fuentes en: {resource}...")

        try:
            repo_info = resolver_repositorio(resource)
            if not repo_info:
                registros_desglosados.append({
                    "resource": resource,
                    "ua": ua,
                    "version_pro": version_pro,
                    "repo_encontrado": "NO",
                    "tiene_builder": "NO",
                    "total_sources_componente": 0,
                    "indice_source": 0,
                    "tipo_fuente_entrada": "NINGUNO",
                    "es_base_datos": "NO"
                })
                continue

            owner, repo, branch = repo_info["owner"], repo_info["repo"], repo_info["branch"]
            archivos = obtener_arbol_archivos(owner, repo, branch)

            builders = [
                f['path'] for f in archivos 
                if f['path'].endswith("Builder.java") and "src/test/" not in f['path']
            ]

            if not builders:
                registros_desglosados.append({
                    "resource": resource,
                    "ua": ua,
                    "version_pro": version_pro,
                    "repo_encontrado": "SI",
                    "tiene_builder": "NO",
                    "total_sources_componente": 0,
                    "indice_source": 0,
                    "tipo_fuente_entrada": "SIN_BUILDER",
                    "es_base_datos": "NO"
                })
                continue

            contenidos = obtener_contenidos_batch_graphql(owner, repo, branch, builders)
            
            for path, codigo in contenidos.items():
                sources = extrae_fuentes_de_builder(codigo)
                num_sources = len(sources)

                if num_sources > 0:
                    for s_idx, src_type in enumerate(sources, 1):
                        es_bd = "SI" if "Jdbc" in src_type else "NO"
                        registros_desglosados.append({
                            "resource": resource,
                            "ua": ua,
                            "version_pro": version_pro,
                            "repo_encontrado": "SI",
                            "tiene_builder": "SI",
                            "total_sources_componente": num_sources,
                            "indice_source": s_idx,
                            "tipo_fuente_entrada": src_type,
                            "es_base_datos": es_bd
                        })
                else:
                    registros_desglosados.append({
                        "resource": resource,
                        "ua": ua,
                        "version_pro": version_pro,
                        "repo_encontrado": "SI",
                        "tiene_builder": "SI",
                        "total_sources_componente": 0,
                        "indice_source": 1,
                        "tipo_fuente_entrada": "SIN_SOURCES_DECLARADOS",
                        "es_base_datos": "NO"
                    })

        except Exception as e:
            print(f"   ⚠️ Error en {resource}: {e}")

        time.sleep(0.05)

    # Exportar DataFrame
    dir_salida = os.path.dirname(ruta_excel_salida)
    if dir_salida:
        os.makedirs(dir_salida, exist_ok=True)

    df = pd.DataFrame(registros_desglosados)
    df.to_excel(ruta_excel_salida, index=False, sheet_name="Todas_Las_Fuentes")

    # Pasar TODAS las fuentes desglosadas al JSON intermedio
    dir_bd_file = os.path.dirname(ANALIZAR_BD_FILE)
    if dir_bd_file:
        os.makedirs(dir_bd_file, exist_ok=True)

    with open(ANALIZAR_BD_FILE, "w", encoding="utf-8") as f:
        json.dump({"data": registros_desglosados}, f, indent=4)

    print(f"\n✅ FASE 1 COMPLETADA:")
    print(f"  - Total registros de fuentes generados: {len(registros_desglosados)}")
    print(f"  - Reporte guardado en: '{ruta_excel_salida}'")


def initialize():
    ejecutar_fase_1(REQUEST_RESULT_FILE, ANALIZAR_RESULT_FILE)


if __name__ == "__main__":
    initialize()