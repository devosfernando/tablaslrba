import re


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
    return texto[start:i-1].strip() if depth == 0 else texto[start:].strip()


def resolver_expresion_generica(expresion, contenidos_repo, depth=0):
    if not expresion or depth > 8:
        return expresion

    exp_limpia = expresion.strip(' "\'\t\r\n')
    if (exp_limpia.startswith('"') and exp_limpia.endswith('"')) or (exp_limpia.startswith("'") and exp_limpia.endswith("'")):
        return exp_limpia.strip(' "\'')

    const_matches = re.findall(r'(?:Constants|[A-Za-z0-9_]+Constants)\.([A-Za-z0-9_]+)', exp_limpia)
    if not const_matches:
        const_matches = [m[1] for m in re.findall(r'(?:([A-Za-z0-9_]+)\.)?([A-Za-z0-9_]+)', exp_limpia)]

    for var_name in const_matches:
        if var_name in ["getOrThrow", "getDefault", "getProperty", "get", "orElseThrow", "builder", "build"]:
            continue
        for _, codigo in contenidos_repo.items():
            pattern_const = rf'(?:public|protected|private)?\s*(?:static)?\s*(?:final)?\s*String\s+{var_name}\s*=\s*([^;]+);'
            match_c = re.search(pattern_const, codigo)
            if match_c:
                res = resolver_expresion_generica(match_c.group(1).strip(' "'), contenidos_repo, depth + 1)
                if res and not res.startswith(var_name):
                    return res

    get_def = re.search(r'\.(?:getOrThrow|getDefault|getProperty|get)\s*\((.*?)\)', exp_limpia, flags=re.DOTALL)
    if get_def:
        args = [a.strip() for a in get_def.group(1).split(',')]
        chosen = args[1] if len(args) == 2 else args[-1] if len(args) > 2 else args[0]
        return resolver_expresion_generica(chosen, contenidos_repo, depth + 1)

    metodo = re.search(r'(?:[\w\.]+\.)?(\w+)\s*\(\)', exp_limpia)
    if metodo:
        nombre_m = metodo.group(1)
        for _, codigo in contenidos_repo.items():
            match_def = re.search(rf'public\s+static\s+String\s+{nombre_m}\s*\(\)\s*\{{(.*?)\}}', codigo, flags=re.DOTALL)
            if match_def:
                ret = re.search(r'return\s+([^;]+);', match_def.group(1), flags=re.DOTALL)
                if ret:
                    return resolver_expresion_generica(ret.group(1).strip(), contenidos_repo, depth + 1)

    return exp_limpia


def depurar_nombre_archivo_parquet(cadena_raw, contenidos_repo, uuaa="cbgh"):
    if not cadena_raw:
        return ""

    exp = cadena_raw.strip()
    if "->" in exp and "[" in exp and "]":
        match_bracket = re.search(r'\[(.*?\.(?:parquet|csv|json|txt))\]', exp, flags=re.IGNORECASE)
        if match_bracket:
            return match_bracket.group(1).strip()

    const_matches = re.findall(r'Constants\.([A-Za-z0-9_]+)', exp)
    if const_matches:
        filename_base, extension = "", ".parquet"
        for c_name in const_matches:
            val = resolver_expresion_generica(f"Constants.{c_name}", contenidos_repo)
            if val and not val.startswith("Constants."):
                if val.startswith(".") or val.lower() in [".parquet", ".csv", ".json", ".txt"]:
                    extension = val
                elif any(k in c_name for k in ["FILENAME", "PHYSICAL", "NAME", "ALIAS", "TABLE", "SOURCE"]):
                    filename_base = val
                elif not filename_base and ("t_" in val.lower() or "bgdt" in val.lower()):
                    filename_base = val
        if filename_base:
            if not filename_base.endswith(extension) and "." not in filename_base:
                filename_base += extension
            return filename_base

    if ".replace(" in exp:
        base_exp = exp.split(".replace(")[0].strip()
        val_base = resolver_expresion_generica(base_exp, contenidos_repo)
        if val_base and val_base != base_exp:
            val_limpio = re.sub(r'\{[A-Za-z0-9_]+\}', '', val_base)
            if not val_limpio.endswith(".parquet") and "." not in val_limpio:
                val_limpio += ".parquet"
            return val_limpio

    if "+" in exp:
        exp_sub = exp.replace('"+UUAA_LOWER+"', uuaa.lower()).replace('"+UUAA+"', uuaa.upper())
        exp_sub = exp_sub.replace('+FILE_EXTENTION', '.parquet').replace('+PARQUET_EXT', '.parquet')
        exp_sub = re.sub(r'["\s+]', '', exp_sub)
        if exp_sub.startswith("t_") or exp_sub.endswith(".parquet"):
            return exp_sub

    res = resolver_expresion_generica(exp, contenidos_repo)
    if res:
        res = res.strip(' "\'\t\r\n').rstrip(')')
    return res


def extraer_fuente_completa_por_indice(contenidos_repo, indice_fuente):
    res = {"archivo": "", "service_name": "N/A"}
    for path, codigo in contenidos_repo.items():
        if not path.endswith("Builder.java"):
            continue

        bloques = codigo.split(".add(")[1:]
        if 0 < indice_fuente <= len(bloques):
            bloque = bloques[indice_fuente - 1]
            if ".physicalName(" in bloque:
                param_phys = extraer_parametro_balanceado(bloque, ".physicalName(")
                if param_phys:
                    res["archivo"] = depurar_nombre_archivo_parquet(param_phys, contenidos_repo)
            elif ".alias(" in bloque:
                param_alias = extraer_parametro_balanceado(bloque, ".alias(")
                if param_alias:
                    res["archivo"] = depurar_nombre_archivo_parquet(param_alias, contenidos_repo)

            if ".serviceName(" in bloque:
                param_service = extraer_parametro_balanceado(bloque, ".serviceName(")
                if param_service:
                    res["service_name"] = resolver_expresion_generica(param_service, contenidos_repo)
            break
    return res