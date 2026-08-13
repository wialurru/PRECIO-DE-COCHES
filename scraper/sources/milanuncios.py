"""Extracción de anuncios de Milanuncios.

Igual que coches.net, Milanuncios incrusta el resultado de búsqueda como
JSON sobre `window.__INITIAL_PROPS__ = JSON.parse("...")`. Aquí interesan
dos bloques:
  - adListPagination.adList.ads: la parrilla normal de resultados (con
    paginación vía ?pagina=N), incluye la descripción completa del vendedor.
  - adCarouselList: en la página de categoría suele traer un carrusel de
    "Anuncios recientes de particulares", útil como señal extra de anuncios
    muy nuevos.

A diferencia de coches.net (que no tiene ninguna opción de orden por fecha
en su API -- se comprobó su enum SORT_FIELDS completo: cc/precio/km/cv/año/
título/relevancia/random, sin fecha), Milanuncios sí soporta pedir los
resultados por fecha de publicación descendente (`?orden=date`, verificado
contra su propio bundle JS: `CRITERIA.DATE = "date"`). Se usa ese orden para
sesgar la cobertura hacia lo más reciente, aunque -- ver nota en
`fetch_listings` -- no es un orden cronológico estricto (hay anuncios
destacados/de pago intercalados), así que se pide un número fijo de
páginas bajo ese orden en vez de intentar "parar en cuanto ya son viejos".
"""
import json
import re

import requests

from .. import config

BASE_URL = "https://www.milanuncios.com/{make}-{model}-de-segunda-mano/"
INITIAL_PROPS_MARKER = '__INITIAL_PROPS__ = JSON.parse("'

# Milanuncios no da la potencia como campo estructurado (a diferencia de
# coches.net): se busca en el título/descripción, tipo "116cv" o "116 CV".
_HP_PATTERN = re.compile(r"(\d{2,3})\s*cv\b", re.IGNORECASE)


def _hp_from_text(*texts):
    for text in texts:
        if not text:
            continue
        m = _HP_PATTERN.search(text)
        if m:
            return int(m.group(1))
    return None


def _extract_initial_props(html: str) -> dict:
    i = html.find(INITIAL_PROPS_MARKER)
    if i == -1:
        raise ValueError("No se encontró __INITIAL_PROPS__ en la página de Milanuncios")
    i += len(INITIAL_PROPS_MARKER)
    j = i
    while not (html[j] == '"' and html[j - 1] != "\\"):
        j += 1
        if j - i > 20_000_000:
            raise ValueError("No se encontró el cierre de __INITIAL_PROPS__")
    raw = html[i:j]
    js_string = json.loads('"' + raw + '"')
    return json.loads(js_string)


def _price_of(ad: dict):
    price = ad.get("price") or {}
    cash = price.get("cashPrice") or {}
    return cash.get("value")


def _tag(ad: dict, tag_type: str):
    for t in ad.get("tags") or []:
        if t.get("type") == tag_type:
            return t.get("text")
    return None


def _year_from_ad(ad: dict):
    txt = _tag(ad, "año")
    if txt and txt.isdigit():
        return int(txt)
    return None


def _km_from_ad(ad: dict):
    txt = _tag(ad, "kilómetros") or ""
    digits = "".join(c for c in txt if c.isdigit())
    return int(digits) if digits else None


def _normalize(ad: dict, display_model: str, make_label: str, model_label: str) -> dict:
    url = ad.get("url") or ""
    return {
        "source": "milanuncios",
        "source_id": str(ad.get("id")),
        "display_model": display_model,
        "make": make_label,
        "model": model_label,
        "year": _year_from_ad(ad),
        "price": _price_of(ad),
        "km": _km_from_ad(ad),
        "fuel": _tag(ad, "combustible"),
        "province": (ad.get("province") or {}).get("name"),
        "city": (ad.get("city") or {}).get("name"),
        "seller_type": ad.get("sellerType"),
        "has_warranty": bool(ad.get("warrantyPeriod")),
        "hp": _hp_from_text(ad.get("title"), ad.get("description")),
        "description": ad.get("description"),
        "title": ad.get("title"),
        "publish_date": ad.get("publishDate") or ad.get("sortDate"),
        "url": "https://www.milanuncios.com" + url if url.startswith("/") else url,
    }


def fetch_listings(display_model: str, make_slug: str, model_slug: str, session: requests.Session,
                    max_pages: int = None) -> list:
    """Nota sobre `orden=date`: sesga los resultados hacia lo más reciente,
    pero no es un orden cronológico estricto (se comprobó con datos reales:
    la proporción de anuncios <15 días por página fluctúa entre el 14% y el
    97% sin bajar de forma monótona, probablemente por anuncios destacados/
    de pago intercalados). Por eso NO se para en cuanto una página parece
    'vieja' -- sería fácil cortar antes de tiempo y perderse anuncios
    recientes que aparecen más adelante. Simplemente se piden más páginas
    que antes (bajo ese orden, que en conjunto sí ayuda) hasta un tope fijo,
    parando antes solo si la propia paginación se acaba (última página con
    menos de 30 anuncios)."""
    max_pages = max_pages or config.MILANUNCIOS_MAX_PAGES
    url = BASE_URL.format(make=make_slug, model=model_slug)
    results = {}
    make_label, model_label = make_slug.title(), model_slug.upper() if len(model_slug) <= 3 else model_slug.title()

    for page in range(1, max_pages + 1):
        params = {"orden": "date"}
        if page > 1:
            params["pagina"] = page
        resp = session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = _extract_initial_props(resp.text)

        pagination = (data.get("adListPagination") or {}).get("adList") or {}
        ads = pagination.get("ads") or []
        if not ads:
            break
        for ad in ads:
            norm = _normalize(ad, display_model, make_label, model_label)
            results[norm["source_id"]] = norm

        if page == 1:
            carousel_ads = []
            for carousel in (data.get("adCarouselList") or {}).get("carousels") or []:
                carousel_ads.extend((carousel.get("adList") or {}).get("ads") or [])
            for ad in carousel_ads:
                norm = _normalize(ad, display_model, make_label, model_label)
                results[norm["source_id"]] = norm

        if len(ads) < 30:  # última página real (resultsPerPage ronda 41)
            break

    return list(results.values())
