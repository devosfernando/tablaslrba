import re
from config.constants import (
    SUFIJOS_COLUMNAS, 
    PALABRAS_RESERVADAS, 
    REGEX_STRICT_FROM, 
    REGEX_SCHEMA_REPLACE, 
    REGEX_HOST_TABLE
)

FORMATOS_EXCLUIDOS = {"PARQUET", "CSV", "JSON", "AVRO", "ORC", "TXT", "DELTA"}


# ==============================================================================
# 1. UTILIDADES DE BASE DE DATOS (JDBC)
# ==============================================================================

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


# ==============================================================================
# 2. MOTOR RESOLUTOR GENÉRICO DE CLASES Y PROPIEDADES
# ==============================================================================

def extraer_parametro_balanceado(texto, patron_inicio):
    idx = texto.find(patron_inicio)
    if idx == -1:
        return ""
    start = idx + len(patron_inicio)
    depth = 1
    i = start
    while i < len(texto) and depth > 0:
        if texto[i] == '(':
            depth += 1
        elif texto[i] == ')':
            depth -= 1
        i += 1
    if depth == 0:
        return texto[start:i-1].strip()
    return texto[start:].strip()


def resolver_expresion_generica(expresion, contenidos_repo, depth=0):
    if not expresion or depth > 8:
        return expresion

    exp_limpia = expresion.strip(' "\'\t\r\n')

    # 1. String literal puro entre comillas "..."
    if (exp_limpia.startswith('"') and exp_limpia.endswith('"')) or (exp_limpia.startswith("'") and exp_limpia.endswith("'")):
        return exp_limpia.strip(' "\'')

    # 2. Búsqueda directa de constante tipo Constants.VARIABLE o VARIABLE
    const_refs = re.findall(r'(?:([A-Za-z0-9_]+)\.)?([A-Za-z0-9_]+)', exp_limpia)
    for clase_or_var, var_name in const_refs:
        if var_name in ["getOrThrow", "getDefault", "getProperty", "get", "orElseThrow", "builder", "build"]:
            continue
            
        for path, codigo in contenidos_repo.items():
            pattern_const = rf'(?:final\s+String|String)\s+{var_name}\s*=\s*([^;]+);'
            match_c = re.search(pattern_const, codigo)
            if match_c:
                val_c = match_c.group(1).strip(' "')
                res = resolver_expresion_generica(val_c, contenidos_repo, depth + 1)
                if res and not res.startswith(var_name):
                    return res

    # 3. Métodos tipo .getOrThrow(...), .getDefault(...), .getProperty(...)
    get_default_match = re.search(r'\.(?:getOrThrow|getDefault|getProperty|get)\s*\((.*?)\)', exp_limpia, flags=re.DOTALL)
    if get_default_match:
        args_str = get_default_match.group(1)
        args = [a.strip() for a in args_str.split(',')]
        if len(args) >= 2:
            chosen_arg = args[1] if len(args) == 2 else args[-1]
            return resolver_expresion_generica(chosen_arg, contenidos_repo, depth + 1)
        elif len(args) == 1 and args[0]:
            return resolver_expresion_generica(args[0], contenidos_repo, depth + 1)

    # 4. Invocaciones a métodos estáticos de clases (ej: Utils.getBtsServiceName())
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
                    return resolver_expresion_generica(retorno, contenidos_repo, depth + 1)

    return exp_limpia


def extraer_fuente_completa_por_indice(contenidos_repo, indice_fuente):
    resultado = {
        "archivo": "",
        "service_name": "N/A"
    }

    for path, codigo in contenidos_repo.items():
        if not path.endswith("Builder.java"):
            continue

        partes = codigo.split(".add(")
        bloques = partes[1:]

        if 0 < indice_fuente <= len(bloques):
            bloque = bloques[indice_fuente - 1]

            # 1. Extraer y resolver Physical Name / Alias
            if ".physicalName(" in bloque:
                param_phys = extraer_parametro_balanceado(bloque, ".physicalName(")
                if param_phys:
                    resultado["archivo"] = resolver_expresion_generica(param_phys, contenidos_repo)
            elif ".alias(" in bloque:
                param_alias = extraer_parametro_balanceado(bloque, ".alias(")
                if param_alias:
                    resultado["archivo"] = resolver_expresion_generica(param_alias, contenidos_repo)

            # 2. Extraer y resolver Service Name
            if ".serviceName(" in bloque:
                param_service = extraer_parametro_balanceado(bloque, ".serviceName(")
                if param_service:
                    resultado["service_name"] = resolver_expresion_generica(param_service, contenidos_repo)

            break

    return resultado