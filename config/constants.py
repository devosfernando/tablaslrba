import re
from dotenv import load_dotenv
import os
load_dotenv()

# 0. INICIO-CONFIGURACIONES GENERALES ---------------------

SOURCE_TMP = "./tmp/"
TARGET_REPORT = "./target_report/"


# request.py files

REQUEST_RESULT_FILE = SOURCE_TMP + "componentes_productivos.json"

# analizar.py files
ANALIZAR_BD_FILE = SOURCE_TMP + "jobs_confirmados_bd.json"
ANALIZAR_RESULT_FILE = SOURCE_TMP + "Reporte_Fase1_Componentes_BD.xlsx"

# result.py files
RESULT_REPORT_FILE = TARGET_REPORT + "Reporte_Rastreo_JDBC_PRO.xlsx"


# 0. FIN-CONFIGURACIONES GENERALES ------------------------


# 1. INICIO - CONFIGURACIÓN GITHUB

GHE_DOMAIN = "bbva.ghe.com"

GHE_TOKEN = os.getenv("GHE_TOKEN")

ORGANIZACIONES_CONOCIDAS = ["platform", "ng-batch", "architecture"]

SUFIJOS_COLUMNAS = (
    "_FILENAME", "_NAME", "_DATE", "_TYPE", "_ID", "_AMOUNT", "_DESC", 
    "_SERVICE", "_PROPERTY", "_STATUS", "_TIME", "_KEY", "_CODE", "_ALIAS",
    "_USER", "_BRANCH", "_ENTITY", "_DAY", "_MONTH", "_YEAR", "_FLAG", "_MARK"
)

PALABRAS_RESERVADAS = {
    "SELECT", "WHERE", "LATERAL", "UNNEST", "DUAL", "ON", "USING", "SET", 
    "AND", "OR", "GROUP", "ORDER", "FORMAT", "STRING", "BBVA", "JSPRK", 
    "V00", "V01", "V02", "DSG", "PRO", "DEV", "INT", "COL", "APP", "SCHEMA",
    "REPLACE", "BUILD", "SQL", "QUERY", "UTILS", "CONSTANTS", "SOURCE", "JDBC",
    "START_DATE", "END_DATE", "ODATE", "ALIAS_SOURCE", "ALIAS_TARGET", "SERVICE_NAME",
    "PHYSICAL_NAME_SOURCE", "SCHEMA_VALUE", "SCHEMA_DB2_DTBG", "ACCOUNTS_SCHEMA_PROPERTY"
}



# REGEX REFINADAS
# Captura específicamente lo que sigue a FROM o JOIN, incluso con variables {SCHEMA} o concatenaciones
REGEX_STRICT_FROM = re.compile(r'\b(?:FROM|JOIN)\s+([a-zA-Z0-9_\`\."{}]+)', re.IGNORECASE)

# Captura patrones de reemplazo de esquema típicos LRBA: replace("{SCHEMA}.BGDTKIT", ...) o "{SCHEMA}.t_kscm_clientes"
REGEX_SCHEMA_REPLACE = re.compile(r'[\'"](?:\{SCHEMA\}|\w+)\.([a-zA-Z0-9_]+)[\'"]', re.IGNORECASE)

# Captura nombres de tablas DB2/Host explícitos (ej: BGDTCMN, BGDTKIT, BGDTTGR, T_KSCM_CLIENTES)
REGEX_HOST_TABLE = re.compile(r'[\'"](BGDT[A-Z0-9]{3}|T_[A-Z0-9_]{3,})[\'"]', re.IGNORECASE)

# ------------------------------------------------ 1. FIN - CONFIGURACIÓN GITHUB -----------------------------------------------


# 2. INICIO - CONFIGURACIÓN CONSOLA ETHER

URL_BASE = "https://bbva-ether-console-front.appspot.com/c/s/ecs-central/gov/v3/reports/versions"

COOKIE_AUTH = os.getenv("COOKIE")


LISTA_UAS = [
    "APIC", "BBGH", "BLOG", "CBGH", "CBGU", "CBTQ", "CCOG", "CDIV", "CGMP",
    "CHVI", "CLBE", "CLNE", "CMCT", "CMOL", "CMTC", "CPAD", "CPDE", "CPME",
    "CQRC", "CQRR", "CRCH", "CREC", "CSAN", "CSLI", "CTSU", "CUBH", "CUGH",
    "CUSU", "CV7H", "CZXH", "J6G7", "JV0D", "KAPI", "KARC", "KBGE", "KBTQ",
    "KCMC", "KCNC", "KCNS", "KCOG", "KCSN", "KLNE", "KMOL", "KPAD", "KPDA",
    "KPDR", "KREC", "KSAN", "KSKR", "KTRA", "KUSU", "L1WI", "LRBA", "MCRR",
    "OCON", "OPEI", "W1BD"
]

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Cookie": COOKIE_AUTH
}

#  ------------------------------------------------2. FIN - CONFIGURACIÓN CONSOLA ETHER ------------------------------------------