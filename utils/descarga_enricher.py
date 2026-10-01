import os
import pandas as pd


def cargar_lookup_descarga(ruta_excel):
    """
    Carga el Excel 'DESCARGA DE TABLAS LRBA.xlsx' y mapea
    cada 'Job / Proyecto' con su lista de tablas detectadas.
    """
    lookup = {}
    if not os.path.exists(ruta_excel):
        alt_ruta = os.path.basename(ruta_excel)
        if os.path.exists(alt_ruta):
            ruta_excel = alt_ruta
        else:
            print(f"⚠️ [LOGGER] No se encontró el archivo de descarga en '{ruta_excel}'.")
            return lookup

    try:
        df = pd.read_excel(ruta_excel)
        for _, row in df.iterrows():
            job = str(row.get('Job / Proyecto', '')).strip()
            tablas_raw = str(row.get('Tablas Detectadas (Únicas)', '')).strip()
            if job and tablas_raw and tablas_raw.lower() != 'nan':
                tables = [t.strip() for t in tablas_raw.split(',') if t.strip()]
                lookup[job] = tables
    except Exception as e:
        print(f"❌ [LOGGER] Error leyendo archivo de descarga: {e}")
    return lookup


def enriquecer_con_descarga_tablas(resultados, ruta_excel_descarga="tmp/DESCARGA DE TABLAS LRBA.xlsx"):
    """
    Reemplaza la información de las fuentes DB/JDBC usando el archivo de cruce
    e imprime un logger con la cantidad exacta de fuentes modificadas.
    """
    lookup = cargar_lookup_descarga(ruta_excel_descarga)
    if not lookup:
        print("⚠️ [LOGGER] Omitiendo paso de enriquecimiento (lookup vacío).")
        return resultados

    jobs_map = {}
    for r in resultados:
        j = r.get("Resource / Job")
        if j not in jobs_map:
            jobs_map[j] = []
        jobs_map[j].append(r)

    # Contadores para el Logger
    fuentes_modificadas = 0
    jobs_modificados = 0

    for job_name, items in jobs_map.items():
        if job_name in lookup:
            tablas_descarga = lookup[job_name]
            num_items = len(items)
            num_tablas = len(tablas_descarga)
            job_cambiado = False

            for idx, item in enumerate(items):
                es_bd = "Jdbc" in item.get("Tipo Fuente Entrada", "") or item.get("es_base_datos") == "SI"
                val_actual = str(item.get("Objeto / Tabla / Archivo Identificado", ""))

                if es_bd or val_actual in ["N/A", "REQUIERE_REVISION_MANUAL", "SIN_TABLAS_DETERMINADAS"]:
                    nuevo_val = tablas_descarga[idx] if num_items == num_tablas else ", ".join(tablas_descarga)
                    
                    # Registrar cambio solo si la información realmente cambió
                    if val_actual != nuevo_val:
                        item["Objeto / Tabla / Archivo Identificado"] = nuevo_val
                        item["Estado"] = "OK"
                        fuentes_modificadas += 1
                        job_cambiado = True

            if job_cambiado:
                jobs_modificados += 1

    # Imprimir resumen claro en consola
    print("\n" + "="*60)
    print("📊 [LOGGER ENRIQUECIMIENTO DESCARGA LRBA]")
    print(f"  - Jobs que coincidieron y se actualizaron: {jobs_modificados}")
    print(f"  - Total de fuentes/filas reemplazadas:    {fuentes_modificadas}")
    print("="*60 + "\n")

    return resultados