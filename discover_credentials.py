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
PRELOAD_LINK_RE = re.compile(
    r'<link[^>]+rel=["\'](?:modulepreload|preload)["\'][^>]*href=["\']([^"\']+\.js[^"\']*)["\']',
    re.IGNORECASE
)

# User-Agent real de Chrome — algunos sitios bloquean o sirven una página
# distinta a "bots" con user-agents genéricos.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
}
MAX_SCRIPTS_TO_CHECK = 25
MAX_FILE_SIZE = 8_000_000  # 8MB — los bundles de React/Vite sin comprimir pueden ser grandes


def _find_url(text: str):
    m = SUPABASE_URL_RE.search(text)
    return m.group(0) if m else None


def _find_key(text: str):
    m = JWT_RE.search(text)
    return m.group(0) if m else None


async def discover_supabase_credentials(homepage_url: str) -> dict | None:
    """
    Devuelve {"project_url": ..., "anon_key": ...} si logra encontrar AMBOS
    datos (pueden venir de archivos distintos, no necesariamente juntos),
    o None si esta app no expone Supabase de forma detectable con este
    método liviano — algunas apps cargan sus credenciales en fragmentos de
    código que solo aparecen después de ejecutar JavaScript en un
    navegador real (React "code splitting"), lo cual este método no
    reproduce. Eso está bien: no todas las apps se van a encontrar así,
    y no es necesario para que el resto de la investigación funcione —
    simplemente esas quedan como "not_found".
    """
    found_url = None
    found_key = None

    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS, follow_redirects=True) as client:
            resp = await client.get(homepage_url)
            html = resp.text

            found_url = found_url or _find_url(html)
            found_key = found_key or _find_key(html)
            if found_url and found_key:
                return {"project_url": found_url, "anon_key": found_key}

            candidate_srcs = SCRIPT_SRC_RE.findall(html) + PRELOAD_LINK_RE.findall(html)
            # sin duplicados, conservando el orden
            seen = set()
            ordered_srcs = []
            for src in candidate_srcs:
                if src not in seen:
                    seen.add(src)
                    ordered_srcs.append(src)

            for src in ordered_srcs[:MAX_SCRIPTS_TO_CHECK]:
                script_url = urljoin(str(resp.url), src)
                try:
                    script_resp = await client.get(script_url)
                    if len(script_resp.content) > MAX_FILE_SIZE:
                        continue
                    text = script_resp.text
                    found_url = found_url or _find_url(text)
                    found_key = found_key or _find_key(text)
                    if found_url and found_key:
                        return {"project_url": found_url, "anon_key": found_key}
                except Exception:
                    continue

            return None
    except Exception:
        return None
