import json
import urllib3
import requests
from config.constants import URL_BASE, COOKIE_AUTH, LISTA_UAS, HEADERS, REQUEST_RESULT_FILE

# Silenciar las advertencias de SSL corporativo no verificado
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def construir_query_params(list_uas, page=0, page_size=500):
    uas_str = ",".join(list_uas)
    q_value = f"uaAcronym=in=({uas_str});techSpecs=in=(112);geography==COL"
    
    return {
        "viewMode": "ENV",
        "page": page,
        "pageSize": page_size,
        "q": q_value
    }


def obtener_y_depurar_componentes_pro(lista_uas):
    componentes_pro = []
    pagina_actual = 0
    pageSize = 500
    total_registros_evaluados = 0

    print("🚀 Iniciando extracción y filtrado de componentes en producción...\n")

    while True:
        params = construir_query_params(lista_uas, page=pagina_actual, page_size=pageSize)
        
        response = requests.get(URL_BASE, headers=HEADERS, params=params, verify=False)

        if response.status_code != 200:
            print(f"❌ Error al consultar la página {pagina_actual}: HTTP {response.status_code}")
            print(f"Respuesta del servidor: {response.text[:200]}")
            break

        # Validar si el cuerpo de la respuesta viene vacío
        if not response.text.strip():
            print(f"⚠️ La respuesta de la página {pagina_actual} está vacía.")
            break

        # Intentar decodificar JSON con manejo de errores explicativo
        try:
            data_json = response.json()
        except requests.exceptions.JSONDecodeError:
            print(f"❌ Error: La respuesta recibida no es un JSON válido.")
            print(f"🔍 Primeros 300 caracteres de la respuesta:\n{response.text[:300]}")
            break

        elementos = data_json if isinstance(data_json, list) else data_json.get("data", [])

        if not elementos:
            print(f"✅ No se encontraron más elementos. Paginado finalizado en la página {pagina_actual}.")
            break

        print(f"📄 Procesando página {pagina_actual} ({len(elementos)} registros recibidos)...")

        for item in elementos:
            total_registros_evaluados += 1
            
            environments = item.get("environments", {})
            pro_env = environments.get("pro", {}).get("COL", {})
            versions_pro = pro_env.get("versions", [])

            # Filtrar solo si tiene versiones activas en el entorno PRO
            if versions_pro and len(versions_pro) > 0:
                componentes_pro.append({
                    "ua": item.get("ua"),
                    "module": item.get("module"),
                    "resource": item.get("resource"),
                    "resourceId": item.get("resourceId"),
                    "kind": item.get("kind"),
                    "lastDeployedVersion": item.get("lastDeployedVersion"),
                    "proVersion": versions_pro[0],
                    "namespacePro": pro_env.get("namespace"),
                    "etherRegion": pro_env.get("etherRegion")
                })

        if len(elementos) < pageSize:
            break

        pagina_actual += 1

    print(f"\n📊 RESUMEN:")
    print(f"  - Total registros evaluados: {total_registros_evaluados}")
    print(f"  - Total componentes desplegados en PRODUCCIÓN: {len(componentes_pro)}")

    return componentes_pro


def initialize():
    resultado = obtener_y_depurar_componentes_pro(LISTA_UAS)

    ARCHIVO_SALIDA = REQUEST_RESULT_FILE
    with open(ARCHIVO_SALIDA, "w", encoding="utf-8") as f:
        json.dump({"data": resultado}, f, indent=4)

    print(f"💾 Archivo guardado exitosamente como '{ARCHIVO_SALIDA}'.")