import json
import re

ARCHIVO_ENTRADA = "test.json"
ARCHIVO_SALIDA = "resultado_namespaces.txt"

def extraer_codigo_4_caracteres(raw_namespace):
    """
    Extrae el código de 4 caracteres según las reglas:
    - Si empieza con 'co.<codigo>.' (ej: co.cbgh.app-id-...) -> CBGH
    - Si contiene '<codigo>.co.' (ej: apic.co.pro) -> APIC
    """
    ns_lower = raw_namespace.lower()
    
    # Caso 1: co.<codigo>. ... (ej: co.cbgh.app-id-1187023.pro)
    match_inicio = re.search(r'^co\.([a-z0-9]{4})\.', ns_lower)
    if match_inicio:
        return match_inicio.group(1).upper()

    # Caso 2: <codigo>.co. ... (ej: apic.co.pro, ctsu.co.pro)
    match_medio = re.search(r'\b([a-z0-9]{4})\.co\.', ns_lower)
    if match_medio:
        return match_medio.group(1).upper()

    return None

def filtrar_y_limpiar_namespaces(ruta_json):
    with open(ruta_json, 'r', encoding='utf-8') as f:
        datos = json.load(f)

    codigos_procesados = set()

    for item in datos:
        raw_namespace = item.get("namespace")
        
        if isinstance(raw_namespace, str):
            ns_lower = raw_namespace.lower()
            
            # Validar que coincida con iniciar en 'co.' o contener '.co.'
            if ns_lower.startswith("co.") or ".co." in ns_lower:
                codigo = extraer_codigo_4_caracteres(raw_namespace)
                if codigo:
                    codigos_procesados.add(codigo)

    return sorted(list(codigos_procesados))

if __name__ == "__main__":
    resultado = filtrar_y_limpiar_namespaces(ARCHIVO_ENTRADA)
    
    # Guardar la lista de códigos limpios en mayúsculas
    with open(ARCHIVO_SALIDA, 'w', encoding='utf-8') as f:
        for codigo in resultado:
            f.write(f"{codigo}\n")
            
    print(f"✅ Proceso completado. Encontrados {len(resultado)} códigos únicos de 4 caracteres.")
    print(f"📁 Resultado guardado en: {ARCHIVO_SALIDA}")