import json
import re
import time
import requests
import pandas as pd
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import urllib3
from config.constants import GHE_DOMAIN, GHE_TOKEN, ORGANIZACIONES_CONOCIDAS, ANALIZAR_BD_FILE, REQUEST_RESULT_FILE, ANALIZAR_RESULT_FILE

# Silenciar advertencias de SSL corporativo
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
    """Localiza el repositorio en organizaciones conocidas."""
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
    """Descarga el contenido de los archivos Builder en un solo lote GraphQL."""
    if not paths:
        return {}

    url_graphql = f"https://{GHE_DOMAIN}/api/graphql"
    queries = []
    
    for idx, path in enumerate(paths[:10]):
        queries.append(f'file_{idx}: object(expression: "{branch}:{path}") {{ ... on Blob {{ text }} }}')
    
    query_body = f'query {{ repository(owner: "{owner}", name: "{repo}") {{ {" ".join(queries)} }} }}'
    
    contenidos = {}
    try:
        resp = session.post(url_graphql, json={"query": query_body}, timeout=10)
        if resp.status_code == 200:
            data = resp.json().get("data", {}).get("repository", {}) or {}
            for idx, path in enumerate(paths[:10]):
                blob = data.get(f"file_{idx}")
                if blob and "text" in blob and blob["text"]:
                    contenidos[path] = blob["text"]
    except Exception:
        pass

    return contenidos

def ejecutar_fase_1(ruta_json_entrada, ruta_excel_salida):
    with open(ruta_json_entrada, 'r', encoding='utf-8') as f:
        data_json = json.load(f)

    componentes = data_json.get("data", [])
    total = len(componentes)
    resultados = []

    print(f"🚀 FASE 1: Identificando rápidamente componentes con acceso a BD ({total} elementos)...\n")

    for idx, item in enumerate(componentes, 1):
        resource = item.get("resource")
        ua = item.get("ua")
        version_pro = item.get("proVersion")

        print(f"[{idx}/{total}] 🔍 Escaneando Builder: {resource}...")

        registro = {
            "resource": resource,
            "ua": ua,
            "version_pro": version_pro,
            "repo_encontrado": "NO",
            "tiene_builder": "NO",
            "conecta_bd": "NO",
            "tipo_conector": "NINGUNO"
        }

        try:
            repo_info = resolver_repositorio(resource)
            if repo_info:
                registro["repo_encontrado"] = "SI"
                owner = repo_info["owner"]
                repo = repo_info["repo"]
                branch = repo_info["branch"]

                archivos = obtener_arbol_archivos(owner, repo, branch)
                
                # Filtrar específicamente archivos Builder.java
                builders = [
                    f['path'] for f in archivos 
                    if f['path'].endswith("Builder.java") and "src/test/" not in f['path']
                ]

                if builders:
                    registro["tiene_builder"] = "SI"
                    contenidos = obtener_contenidos_batch_graphql(owner, repo, branch, builders)

                    for path, codigo in contenidos.items():
                        if "Source.Jdbc" in codigo or "RegisterSparkBuilder" in codigo:
                            registro["conecta_bd"] = "SI"
                            
                            # Identificar sub-tipo de conector
                            if "Source.Jdbc.NativeQuery" in codigo:
                                registro["tipo_conector"] = "Source.Jdbc.NativeQuery"
                            elif "Source.Jdbc.Basic" in codigo:
                                registro["tipo_conector"] = "Source.Jdbc.Basic"
                            else:
                                registro["tipo_conector"] = codigo
                            break
        except Exception as e:
            print(f"   ⚠️ Error en {resource}: {e}")

        resultados.append(registro)
        time.sleep(0.05)

    # Convertir a DataFrame y guardar Excel
    df = pd.DataFrame(resultados)
    df.columns = [
        "Resource / Job",
        "UA",
        "Versión PRO",
        "Repo Encontrado",
        "Tiene Builder Java",
        "Conecta BD (Source.Jdbc)",
        "Tipo Conector"
    ]

    df.to_excel(ruta_excel_salida, index=False, sheet_name="Fase1_Conexion_BD")

    # Guardar también una lista filtrada en JSON con solo los componentes con "conecta_bd = SI"
    jobs_con_bd = [r for r in resultados if r["conecta_bd"] == "SI"]
    with open(ANALIZAR_BD_FILE, "w", encoding="utf-8") as f:
        json.dump({"data": jobs_con_bd}, f, indent=4)

    print(f"\n✅ FASE 1 COMPLETADA:")
    print(f"  - Total componentes evaluados: {total}")
    print(f"  - Componentes confirmados con acceso a BD: {len(jobs_con_bd)}")
    print(f"  - Reporte Excel generado: '{ruta_excel_salida}'")
    print(f"  - JSON con lista filtrada guardado para Fase 2: 'jobs_confirmados_bd.json'")

def initialize():
    ejecutar_fase_1(REQUEST_RESULT_FILE, ANALIZAR_RESULT_FILE)