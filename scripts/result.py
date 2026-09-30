import os
import re
import json
import time
import urllib3
import requests
import pandas as pd
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from config.constants import (
    GHE_DOMAIN, 
    GHE_TOKEN, 
    SUFIJOS_COLUMNAS, 
    RESULT_INVENTARIO, 
    RESULT_REPORT_FILE, 
    ORGANIZACIONES_CONOCIDAS, 
    ANALIZAR_BD_FILE, 
    PALABRAS_RESERVADAS, 
    REGEX_STRICT_FROM, 
    REGEX_SCHEMA_REPLACE, 
    REGEX_HOST_TABLE
)

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

FORMATOS_EXCLUIDOS = {"PARQUET", "CSV", "JSON", "AVRO", "ORC", "TXT", "DELTA"}


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
    if not candidato or not isinstance(candidato, str):
        return False
    
    cand_upper = candidato.strip('`"() \t\n\r\'').upper()
    
    if cand_upper in FORMATOS_EXCLUIDOS or cand_upper in PALABRAS_RESERVADAS or len(cand_upper) < 4:
        return False

    if "." in cand_upper:
        cand_upper = cand_upper.split(".")[-1]

    if any(cand_upper.endswith(sufijo) for sufijo in SUFIJOS_COLUMNAS):
        return False

    if cand_upper.startswith("BGDT") or cand_upper.startswith("T_") or cand_upper.startswith("TABLA_"):
        return cand_upper

    if cand_upper.isalpha() and 5 <= len(cand_upper) <= 12:
        if not any(cand_upper.startswith(p) for p in ["KIT_", "CLI_", "CMN_", "NDC_"]):
            return cand_upper

    return False


def resolver_expresion_recursiva(expresion, contenidos_repo, depth=0):
    """
    Rastrea recursivamente la variable o método hasta obtener SOLO el string del nombre del archivo en limpio.
    """
    if not expresion or depth > 6:
        return expresion

    exp_limpia = expresion.strip(' "\'\t\r\n')

    # 1. String literal puro entre comillas "..."
    if (exp_limpia.startswith('"') and exp_limpia.endswith('"')) or (exp_limpia.startswith("'") and exp_limpia.endswith("'")):
        return exp_limpia.strip(' "\'')

    # 2. Si encuentra .getDefault(key, defaultValue) -> Toma el segundo argumento (defaultValue)
    get_default_match = re.search(r'\.(?:getDefault|getProperty|get)\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)', exp_limpia, flags=re.DOTALL)
    if get_default_match:
        segundo_arg = get_default_match.group(2).strip()
        return resolver_expresion_recursiva(segundo_arg, contenidos_repo, depth + 1)

    # 3. Si es llamada a un método ej: Utils.getPropertyFileBGDTCLIPhysicalName()
    metodo_match = re.search(r'(?:[\w\.]+\.)?(\w+)\s*\(\)', exp_limpia)
    if metodo_match:
        nombre_metodo = metodo_match.group(1)
        for path, codigo in contenidos_repo.items():
            pattern_def = rf'public\s+static\s+String\s+{nombre_metodo}\s*\(\)\s*\{{(.*?)\}}'
            match_def = re.search(pattern_def, codigo, flags=re.DOTALL)
            if match_def:
                cuerpo = match_def.group(1)
                return_match = re.search(r'return\s+([^;]+);', cuerpo, flags=re.DOTALL)
                if return_match:
                    retorno = return_match.group(1).strip()
                    return resolver_expresion_recursiva(retorno, contenidos_repo, depth + 1)

    # 4. Si es una constante o variable en Constants.java o similar
    const_match = re.search(r'(?:[\w\.]+\.)?(\w+)', exp_limpia)
    if const_match:
        nombre_const = const_match.group(1)
        for path, codigo in contenidos_repo.items():
            pattern_const = rf'(?:final\s+String|String)\s+{nombre_const}\s*=\s*([^;]+);'
            match_c = re.search(pattern_const, codigo)
            if match_c:
                val_c = match_c.group(1).strip(' "')
                return resolver_expresion_recursiva(val_c, contenidos_repo, depth + 1)

    return exp_limpia


def extraer_archivo_especifico_por_indice(contenidos_repo, indice_fuente):
    """
    Localiza el bloque .add(...) exacto correspondiente a la posición indice_fuente (1..N)
    en el Builder.java y resuelve unicamente su archivo.
    """
    for path, codigo in contenidos_repo.items():
        if not path.endswith("Builder.java"):
            continue

        # Dividir el código del Builder en bloques individuales de .add(...)
        bloques = re.findall(r'(\.add\s*\(\s*Source\.[^;]+?\.build\s*\(\s*\)\s*\))', codigo, flags=re.DOTALL)
        
        if not bloques:
            # Fallback en caso de sintaxis ligeramente distinta
            bloques = re.split(r'\.add\s*\(', codigo)[1:]

        if 0 < indice_fuente <= len(bloques):
            bloque_objetivo = bloques[indice_fuente - 1]

            # Intentar con .physicalName(...)
            match_phys = re.findall(r'\.physicalName\(((?:[^()]+|\([^()]*\))*)\)', bloque_objetivo)
            if match_phys:
                return resolver_expresion_recursiva(match_phys[0], contenidos_repo)

            # Si no tiene physicalName, probar con .alias(...)
            match_alias = re.findall(r'\.alias\(((?:[^()]+|\([^()]*\))*)\)', bloque_objetivo)
            if match_alias:
                return resolver_expresion_recursiva(match_alias[0], contenidos_repo)

    return ""


def extraer_tablas_estrictas(contenidos_repo):
    tablas = set()
    for path, codigo in contenidos_repo.items():
        if not path.endswith(".java") and not path.endswith(".sql"):
            continue

        codigo_limpio = re.sub(r'//.*$', '', codigo, flags=re.MULTILINE)
        codigo_limpio = re.sub(r'/\*.*?\*/', '', codigo_limpio, flags=re.DOTALL)

        for match in REGEX_SCHEMA_REPLACE.findall(codigo_limpio):
            t_valida = es_tabla_valida(match)
            if t_valida:
                tablas.add(t_valida)

        for match in REGEX_STRICT_FROM.findall(codigo_limpio):
            t_valida = es_tabla_valida(match)
            if t_valida:
                tablas.add(t_valida)

        for match in REGEX_HOST_TABLE.findall(codigo_limpio):
            t_valida = es_tabla_valida(match)
            if t_valida:
                tablas.add(t_valida)

    return sorted(list(tablas))


def ejecutar_fase_2(ruta_json_fase1, ruta_excel_salida):
    print(f"🚀 FASE 2: Extrayendo identificadores/tablas y resolviendo nombres de archivo en claro...\n")

    if not os.path.exists(ruta_json_fase1):
        print(f"⚠️ El archivo '{ruta_json_fase1}' no existe.")
        return

    with open(ruta_json_fase1, 'r', encoding='utf-8') as f:
        data_json = json.load(f)

    todas_las_fuentes = data_json.get("data", [])
    total = len(todas_las_fuentes)
    resultados_finales = []

    for idx, item in enumerate(todas_las_fuentes, 1):
        resource = item.get("resource")
        ua = item.get("ua")
        version_pro = item.get("version_pro")
        tipo_fuente = item.get("tipo_fuente_entrada")
        total_sources = item.get("total_sources_componente", 1)
        idx_source = item.get("indice_source", 1)
        es_bd = item.get("es_base_datos", "NO")

        print(f"[{idx}/{total}] 🔬 Rastreando en {resource} (Fuente {idx_source}/{total_sources}: {tipo_fuente})...")

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

                    # 1. Fuentes de tipo ARCHIVO (Parquet, CSV, etc.)
                    if es_bd == "NO":
                        arch_limpio = extraer_archivo_especifico_por_indice(contenidos, idx_source)
                        if arch_limpio:
                            registro["Objeto / Tabla / Archivo Identificado"] = arch_limpio
                            registro["Estado"] = "OK"
                        else:
                            nombre_formato = tipo_fuente.split(".")[-1].upper() if "." in tipo_fuente else tipo_fuente
                            registro["Objeto / Tabla / Archivo Identificado"] = f"ARCHIVO_{nombre_formato}"

                    # 2. Fuentes de tipo BASE DE DATOS (JDBC)
                    else:
                        tablas = extraer_tablas_estrictas(contenidos)
                        registro["Objeto / Tabla / Archivo Identificado"] = ", ".join(tablas) if tablas else "REQUIERE_REVISION_MANUAL"
                        registro["Estado"] = "OK" if tablas else "SIN_TABLAS_DETERMINADAS"

        except Exception as e:
            print(f"   ⚠️ Error en {resource}: {e}")
            registro["Estado"] = f"ERROR: {str(e)}"

        resultados_finales.append(registro)
        time.sleep(0.05)

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

    print(f"\n✅ PROCESO FINALIZADO:")
    print(f"  - Total fuentes clasificadas en el inventario: {len(resultados_finales)}")
    print(f"  - Reporte Excel final: '{ruta_excel_salida}'")


def initialize():
    ejecutar_fase_2(ANALIZAR_BD_FILE, RESULT_REPORT_FILE)


if __name__ == "__main__":
    initialize()