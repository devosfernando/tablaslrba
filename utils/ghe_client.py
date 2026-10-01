import urllib3
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from config.constants import GHE_DOMAIN, GHE_TOKEN, ORGANIZACIONES_CONOCIDAS

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {GHE_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
})
session.verify = False

retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))

CACHE_REPOS = {}
CACHE_CONTENIDOS = {}


def resolver_repositorio(resource_name):
    repo_slug = resource_name.lower()
    if repo_slug in CACHE_REPOS:
        return CACHE_REPOS[repo_slug]

    for org in ORGANIZACIONES_CONOCIDAS:
        try:
            url = f"https://{GHE_DOMAIN}/api/v3/repos/{org}/{repo_slug}"
            resp = session.get(url, timeout=8)
            if resp.status_code == 200:
                datos = resp.json()
                res = {"owner": org, "repo": repo_slug, "branch": datos.get("default_branch", "master")}
                CACHE_REPOS[repo_slug] = res
                return res
        except Exception:
            pass

    CACHE_REPOS[repo_slug] = None
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
    
    cache_key = f"{owner}/{repo}@{branch}"
    if cache_key in CACHE_CONTENIDOS:
        return CACHE_CONTENIDOS[cache_key]

    url_graphql = f"https://{GHE_DOMAIN}/api/graphql"
    queries = [f'file_{i}: object(expression: "{branch}:{p}") {{ ... on Blob {{ text }} }}' for i, p in enumerate(paths[:30])]
    query_body = f'query {{ repository(owner: "{owner}", name: "{repo}") {{ {" ".join(queries)} }} }}'
    contenidos = {}

    try:
        resp = session.post(url_graphql, json={"query": query_body}, timeout=12)
        if resp.status_code == 200:
            data = resp.json().get("data", {}).get("repository", {}) or {}
            for i, p in enumerate(paths[:30]):
                blob = data.get(f"file_{i}")
                if blob and "text" in blob and blob["text"]:
                    contenidos[p] = blob["text"]
    except Exception:
        pass

    CACHE_CONTENIDOS[cache_key] = contenidos
    return contenidos