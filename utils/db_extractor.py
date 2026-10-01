import re
from config.constants import SUFIJOS_COLUMNAS, PALABRAS_RESERVADAS, REGEX_STRICT_FROM, REGEX_SCHEMA_REPLACE, REGEX_HOST_TABLE

FORMATOS_EXCLUIDOS = {"PARQUET", "CSV", "JSON", "AVRO", "ORC", "TXT", "DELTA"}


def es_tabla_valida(candidato):
    if not candidato or not isinstance(candidato, str):
        return False
    cand_upper = candidato.strip('`"() \t\n\r\'').upper()
    
    if cand_upper in FORMATOS_EXCLUIDOS or cand_upper in PALABRAS_RESERVADAS or len(cand_upper) < 4:
        return False

    if "." in cand_upper:
        cand_upper = cand_upper.split(".")[-1]

    if any(cand_upper.endswith(s) for s in SUFIJOS_COLUMNAS):
        return False

    # Aceptar estrictamente patrones de tablas corporativas (T_..., BGDT..., TABLA_...)
    if cand_upper.startswith(("BGDT", "T_", "TABLA_")):
        return cand_upper

    return False


def extraer_tablas_estrictas(contenidos_repo):
    tablas = set()
    for path, codigo in contenidos_repo.items():
        if not path.endswith((".java", ".sql")):
            continue
        limpio = re.sub(r'//.*$', '', codigo, flags=re.MULTILINE)
        limpio = re.sub(r'/\*.*?\*/', '', limpio, flags=re.DOTALL)

        for reg in [REGEX_SCHEMA_REPLACE, REGEX_STRICT_FROM, REGEX_HOST_TABLE]:
            for match in reg.findall(limpio):
                t = es_tabla_valida(match)
                if t:
                    tablas.add(t)
    return sorted(list(tablas))