import json
import re
import time
import requests
import pandas as pd
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import urllib3
from config.constants import GHE_DOMAIN, GHE_TOKEN, ORGANIZACIONES_CONOCIDAS, REQUEST_RESULT_FILE, ANALIZAR_RESULT_FILE, ANALIZAR_BD_FILE,PALABRAS_RESERVADAS, REGEX_STRICT_FROM, REGEX_SCHEMA_REPLACE, REGEX_HOST_TABLE


# Silenciar advertencias de SSL corporativo
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. CONFIGURACIÓN


session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {GHE_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
})
session.verify = False

retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))



# Palabras clave y sufijos típicos de COLUMNAS / CAMPOS que NO son tablas


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
    return contenidos

def es_tabla_valida(candidato):
    """Valida si un string corresponde a una tabla de base de datos y no a una columna o constante."""
    if not candidato or not isinstance(candidato, str):
        return False
    
    cand_upper = candidato.strip('`"() \t\n\r\'').upper()
    
    # Remover prefijos de esquema si vienen incluidos
    if "." in cand_upper:
        cand_upper = cand_upper.split(".")[-1]

    # Descartar palabras reservadas o cortas
    if cand_upper in PALABRAS_RESERVADAS or len(cand_upper) < 4:
        return False

    # Descartar si termina con sufijos típicos de columnas / campos
    if any(cand_upper.endswith(sufijo) for sufijo in SUFIJOS_COLUMNAS):
        return False

    # Aceptar si cumple patrón de tabla Host (BGDT...) o tabla de negocio (T_...)
    if cand_upper.startswith("BGDT") or cand_upper.startswith("T_") or cand_upper.startswith("TABLA_"):
        return cand_upper

    # Si es un nombre en mayúsculas limpio sin guiones de columna (ej: CONTRATOS, CLIENTES)
    if cand_upper.isalpha() and 5 <= len(cand_upper) <= 12:
        # Verificar que no sea un nombre de columna conocido
        if not cand_upper.startswith("KIT_") and not cand_upper.startswith("CLI_") and not cand_upper.startswith("CMN_") and not cand_upper.startswith("NDC_"):
            return cand_upper

    return False

def extraer_tablas_estrictas(contenidos_repo):
    """Analiza los archivos Java del repositorio buscando exclusivamente la entidad en el FROM / JOIN."""
    tablas = set()

    for path, codigo in contenidos_repo.items():
        if not path.endswith(".java") and not path.endswith(".sql"):
            continue

        codigo_limpio = re.sub(r'//.*$', '', codigo, flags=re.MULTILINE)
        codigo_limpio = re.sub(r'/\*.*?\*/', '', codigo_limpio, flags=re.DOTALL)

        # 1. Reemplazos de Plantilla de Esquema: replace("{SCHEMA}.BGDTKIT", ...)
        for match in REGEX_SCHEMA_REPLACE.findall(codigo_limpio):
            t_valida = es_tabla_valida(match)
            if t_valida:
                tablas.add(t_valida)

        # 2. Sentencias FROM / JOIN explícitas
        for match in REGEX_STRICT_FROM.findall(codigo_limpio):
            t_valida = es_tabla_valida(match)
            if t_valida:
                tablas.add(t_valida)

        # 3. Coincidencias de Tablas Host/DB2 típicas ("BGDT...", "T_...")
        for match in REGEX_HOST_TABLE.findall(codigo_limpio):
            t_valida = es_tabla_valida(match)
            if t_valida:
                tablas.add(t_valida)

    return sorted(list(tablas))

def ejecutar_fase_2(ruta_json_fase1, ruta_excel_salida):
    with open(ruta_json_fase1, 'r', encoding='utf-8') as f:
        data_json = json.load(f)

    todos_los_jobs = data_json.get("data", [])
    jobs = [item for item in todos_los_jobs if item.get("tipo_conector") == "Source.Jdbc.NativeQuery"]
    total = len(jobs)
    resultados_finales = []

    print(f"🚀 FASE 2 REFINADA: Extracción estricta de tablas de DB2 para {total} jobs...\n")

    for idx, item in enumerate(jobs, 1):
        resource = item.get("resource")
        ua = item.get("ua")
        version_pro = item.get("version_pro")
        tipo_conector = item.get("tipo_conector")

        print(f"[{idx}/{total}] 🔬 Extrayendo tabla física en: {resource}...")

        registro = {
            "Resource / Job": resource,
            "UA": ua,
            "Versión PRO": version_pro,
            "Tipo Conector": tipo_conector,
            "Tablas Identificadas": "",
            "Total Tablas": 0,
            "Estado": "NO_ENCONTRADO"
        }

        try:
            repo_info = resolver_repositorio(resource)
            if repo_info:
                owner = repo_info["owner"]
                repo = repo_info["repo"]
                branch = repo_info["branch"]

                archivos = obtener_arbol_archivos(owner, repo, branch)
                
                # Cargar archivos Java relevantes (Builder, Query, Constants, etc.)
                archivos_interes = [
                    f['path'] for f in archivos 
                    if (f['path'].endswith(".java") or f['path'].endswith(".sql")) 
                    and "src/test/" not in f['path']
                ]

                if archivos_interes:
                    contenidos = obtener_contenidos_batch_graphql(owner, repo, branch, archivos_interes)
                    
                    tablas = extraer_tablas_estrictas(contenidos)
                    
                    registro["Tablas Identificadas"] = ", ".join(tablas) if tablas else "REQUIERE_REVISION_MANUAL"
                    registro["Total Tablas"] = len(tablas)
                    registro["Estado"] = "OK" if tablas else "SIN_TABLAS_DETERMINADAS"

        except Exception as e:
            print(f"   ⚠️ Error procesando {resource}: {e}")
            registro["Estado"] = f"ERROR: {str(e)}"

        resultados_finales.append(registro)
        time.sleep(0.05)

    df = pd.DataFrame(resultados_finales)
    df.to_excel(ruta_excel_salida, index=False, sheet_name="Rastreo_NativeQuery_Limpio")

    with open("inventario_native_query_tablas_limpio.json", "w", encoding="utf-8") as f:
        json.dump({"data": resultados_finales}, f, indent=4)

    print(f"\n✅ PROCESO FINALIZADO:")
    print(f"  - Reporte limpio generado en Excel: '{ruta_excel_salida}'")

if __name__ == "__main__":
    ejecutar_fase_2(ANALIZAR_BD_FILE, RESULT_REPORT_FILE)