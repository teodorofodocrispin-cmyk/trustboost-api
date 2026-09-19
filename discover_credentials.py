"""
discover_credentials.py

Dado el link público de una app (su homepage), intenta encontrar
automáticamente su URL de proyecto Supabase y su anon key — los mismos
dos datos que hoy tienes que copiar a mano desde las herramientas de
desarrollador del navegador.

Cómo funciona: la anon key de Supabase, por diseño, TIENE que viajar
hasta el navegador del visitante para que la app funcione — no hay forma
de que una app la use sin exponerla en algún archivo que el navegador
descarga (el HTML mismo, o uno de los archivos .js que carga). Este
módulo descarga esos mismos archivos (los que cualquier visitante ya
descarga) y busca los dos patrones reconocibles:
  - una URL con forma https://xxxxx.supabase.co
  - una anon key, que siempre es un JWT y por lo tanto siempre empieza
    con "eyJ"

No hace nada que un navegador normal no haga ya — solo automatiza la
búsqueda de un patrón en texto público.
"""

import re
import httpx
from urllib.parse import urljoin

SUPABASE_URL_RE = re.compile(r"https://[a-z0-9]{15,25}\.supabase\.co")
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
SCRIPT_SRC_RE = re.compile(r'<script[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TrustBoostResearch/1.0)"}
MAX_SCRIPTS_TO_CHECK = 8
MAX_FILE_SIZE = 3_000_000  # no descargar archivos de más de 3MB, no vale la pena


def _extract_from_text(text: str):
    url_match = SUPABASE_URL_RE.search(text)
    key_match = JWT_RE.search(text)
    if url_match and key_match:
        return {"project_url": url_match.group(0), "anon_key": key_match.group(0)}
    return None


async def discover_supabase_credentials(homepage_url: str) -> dict | None:
    """
    Devuelve {"project_url": ..., "anon_key": ...} si logra encontrarlos,
    o None si esta app no expone Supabase de forma detectable (puede
    usar otro backend, o cargar las credenciales de una forma que este
    método simple no cubre — eso está bien, no todas las apps se van a
    encontrar, y no es necesario para que el resto de la investigación
    funcione).
    """
    try:
        async with httpx.AsyncClient(timeout=12, headers=HEADERS, follow_redirects=True) as client:
            resp = await client.get(homepage_url)
            html = resp.text

            found = _extract_from_text(html)
            if found:
                return found

            script_srcs = SCRIPT_SRC_RE.findall(html)[:MAX_SCRIPTS_TO_CHECK]
            for src in script_srcs:
                script_url = urljoin(str(resp.url), src)
                try:
                    script_resp = await client.get(script_url)
                    if len(script_resp.content) > MAX_FILE_SIZE:
                        continue
                    found = _extract_from_text(script_resp.text)
                    if found:
                        return found
                except Exception:
                    continue

            return None
    except Exception:
        return None
