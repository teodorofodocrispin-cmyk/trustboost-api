"""
dependency_check.py

Revisa un package.json en busca de paquetes que probablemente fueron
"alucinados" por un modelo de IA (slopsquatting) — nombres que no
existen de verdad, o que existen pero tienen un perfil sospechoso
(muy nuevos, muy pocas descargas).

Deliberadamente NO mantiene ninguna lista propia de paquetes
maliciosos — eso se volvería vieja rápido y sería trabajo de
mantenimiento constante para un fundador solo. En su lugar, consulta
en vivo dos fuentes gratuitas, sin necesitar ninguna API key:
- El registro público de npm (¿existe el paquete? ¿qué tan nuevo es?)
- OSV.dev, la base de datos de vulnerabilidades de código abierto de
  Google (¿tiene vulnerabilidades conocidas?)
"""

import json
import httpx
from datetime import datetime, timezone

NPM_REGISTRY = "https://registry.npmjs.org"
NPM_DOWNLOADS = "https://api.npmjs.org/downloads/point/last-month"
OSV_API = "https://api.osv.dev/v1/query"

SUSPICIOUS_AGE_DAYS = 90
SUSPICIOUS_DOWNLOAD_THRESHOLD = 50


async def _check_one_package(client: httpx.AsyncClient, name: str) -> dict | None:
    """Revisa un solo paquete. Devuelve None si parece normal, o un
    dict con la razón de sospecha si no."""
    try:
        r = await client.get(f"{NPM_REGISTRY}/{name}", timeout=8)
    except Exception:
        return None  # si npm no responde, no acusamos nada — evita falsos positivos

    if r.status_code == 404:
        return {
            "package": name,
            "severity": "CRITICAL",
            "reason": (
                "Package does not exist on npm — this looks like an AI-hallucinated "
                "package name (slopsquatting risk). If an attacker has registered this "
                "exact name, installing it could deliver malware instead of the "
                "library you expected."
            ),
        }
    if r.status_code != 200:
        return None

    try:
        data = r.json()
    except Exception:
        return None

    is_new = False
    created = (data.get("time") or {}).get("created")
    if created:
        try:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - created_dt).days
            is_new = age_days < SUSPICIOUS_AGE_DAYS
        except Exception:
            pass

    downloads = None
    try:
        dr = await client.get(f"{NPM_DOWNLOADS}/{name}", timeout=8)
        if dr.status_code == 200:
            downloads = dr.json().get("downloads")
    except Exception:
        pass

    if is_new and downloads is not None and downloads < SUSPICIOUS_DOWNLOAD_THRESHOLD:
        return {
            "package": name,
            "severity": "PRIVATE",
            "reason": (
                f"Published recently and has very few downloads ({downloads}/month) — "
                "could be a newly-registered package squatting on a name an AI model "
                "hallucinates. Worth a manual look before trusting it in production."
            ),
        }

    # Chequeo de vulnerabilidades conocidas — independiente de si el
    # paquete parece nuevo o no.
    try:
        ov = await client.post(
            OSV_API, json={"package": {"name": name, "ecosystem": "npm"}}, timeout=8
        )
        if ov.status_code == 200:
            vulns = ov.json().get("vulns", [])
            if vulns:
                ids = ", ".join(v.get("id", "") for v in vulns[:3])
                return {
                    "package": name,
                    "severity": "PRIVATE",
                    "reason": f"Has known vulnerabilities on OSV.dev: {ids}",
                }
    except Exception:
        pass

    return None


async def check_package_json(package_json_text: str) -> dict:
    """Revisa todas las dependencias listadas en un package.json.
    Devuelve un resumen con los paquetes sospechosos encontrados."""
    try:
        data = json.loads(package_json_text)
    except Exception:
        return {"status": "error", "message": "Invalid package.json — could not parse as JSON."}

    deps: dict = {}
    deps.update(data.get("dependencies", {}) or {})
    deps.update(data.get("devDependencies", {}) or {})

    if not deps:
        return {"status": "success", "packages_checked": 0, "findings": []}

    findings = []
    async with httpx.AsyncClient() as client:
        for name in deps.keys():
            result = await _check_one_package(client, name)
            if result:
                findings.append(result)

    return {
        "status": "success",
        "packages_checked": len(deps),
        "findings": findings,
    }
