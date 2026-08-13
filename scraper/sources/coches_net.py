"""Extracción de anuncios de coches.net.

coches.net renderiza la página en servidor e incrusta el resultado de la
búsqueda como JSON en `window.__INITIAL_PROPS__ = JSON.parse("...")`.
Se pide esa página con un User-Agent de navegador normal y se parsea ese
JSON directamente -- es la fuente real de datos que usa el propio sitio,
no una aproximación por HTML/CSS que se rompería con cualquier rediseño.
"""
import json
import requests

from .. import config

SEARCH_URL = "https://www.coches.net/segunda-mano/"
INITIAL_PROPS_MARKER = '__INITIAL_PROPS__ = JSON.parse("'


def _extract_initial_props(html: str) -> dict:
    i = html.find(INITIAL_PROPS_MARKER)
    if i == -1:
        raise ValueError("No se encontró __INITIAL_PROPS__ en la página de coches.net")
    i += len(INITIAL_PROPS_MARKER)
    j = i
    while not (html[j] == '"' and html[j - 1] != "\\"):
        j += 1
        if j - i > 20_000_000:
            raise ValueError("No se encontró el cierre de __INITIAL_PROPS__")
    raw = html[i:j]
    js_string = json.loads('"' + raw + '"')
    return json.loads(js_string)


def _normalize(item: dict, display_model: str) -> dict:
    return {
        "source": "coches_net",
        "source_id": str(item.get("id")),
        "display_model": display_model,
        "make": item.get("make"),
        "model": item.get("model"),
        "year": item.get("year"),
        "price": item.get("price"),
        "km": item.get("km"),
        "fuel": item.get("fuelType"),
        "province": (item.get("location") or {}).get("mainProvince"),
        "city": (item.get("location") or {}).get("cityLiteral"),
        "seller_type": "professional" if item.get("isProfessional") else "private",
        "has_warranty": item.get("hasWarranty"),
        "description": None,  # el listado no trae descripción libre, solo el detalle del anuncio la tiene
        "title": item.get("title"),
        "publish_date": item.get("creationDate") or item.get("publicationDate"),
        "url": "https://www.coches.net" + item["url"] if item.get("url", "").startswith("/") else item.get("url"),
    }


def fetch_listings(display_model: str, make_id: int, model_id: int, session: requests.Session,
                    max_pages: int = None) -> list:
    max_pages = max_pages or config.MAX_PAGES_PER_SOURCE
    results = []
    for page in range(1, max_pages + 1):
        params = {"makeId": make_id, "modelId": model_id, "page": page}
        resp = session.get(SEARCH_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = _extract_initial_props(resp.text)
        ir = data.get("initialResults") or {}
        items = ir.get("items") or []
        if not items:
            break
        for item in items:
            results.append(_normalize(item, display_model))
        total_pages = ir.get("totalPages") or 1
        if page >= total_pages:
            break
    return results
