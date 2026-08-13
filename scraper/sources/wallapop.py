"""Extracción de anuncios de Wallapop vía Playwright (navegador real).

Wallapop bloquea con 403 (CloudFront) cualquier petición HTTP directa: ni
`requests` con cabeceras de navegador, ni pasar por un proxy lector (se
probó con r.jina.ai y también lo bloqueó), ni pegarle directamente a su
API pública sin contexto de navegador. La única vía que queda es un
navegador real que ejecute el JS de la SPA y dispare sus propias llamadas
a la API -- aquí NO se vuelve a golpear esa API a mano, se intercepta la
respuesta que el propio Wallapop pide al cargar la página.

⚠️ IMPORTANTE -- este archivo no se ha podido probar contra el sitio real.
El entorno donde se escribió no tiene salida a red para procesos de
navegador en absoluto (se confirmó lanzando Chromium headless contra
https://example.com/, que también falla con ERR_CONNECTION_RESET; no es
un bloqueo de Wallapop, es una limitación del sandbox). Hace falta
ejecutar esto desde una máquina con red normal y depurarlo con
`scraper/tools/inspect_wallapop.py`, que vuelca las respuestas de red
reales para poder ajustar aquí los nombres de campo si no coinciden con
lo que se ha adivinado.

No se importa desde scraper/run.py (el pipeline automático de GitHub
Actions no necesita Playwright, que es pesado y no funciona sin más en
un runner). Se ejecuta aparte, en local, con:
    pip install -r requirements-wallapop.txt
    playwright install chromium
    python -m scraper.run_wallapop
"""
import re
import unicodedata

SEARCH_URL = "https://es.wallapop.com/coches-segunda-mano/{slug}"

# Fragmentos de URL que identifican una respuesta de red como "datos de
# búsqueda" de Wallapop. Es una lista porque no sabemos a ciencia cierta
# cuál usa la versión actual del sitio -- inspect_wallapop.py ayuda a
# confirmar/ampliar esta lista con datos reales.
API_URL_HINTS = ("api.wallapop.com", "/search", "/api/v3")

# Claves candidatas para cada campo, en orden de preferencia, porque no
# está confirmado el esquema exacto del JSON que devuelve Wallapop.
ID_KEYS = ("id", "objectId", "itemId")
TITLE_KEYS = ("title", "name")
PRICE_KEYS = ("price", "cashPrice", "amount")
DESCRIPTION_KEYS = ("description", "content", "storytelling")
LOCATION_KEYS = ("location", "city")
DATE_KEYS = ("creationDate", "createdDate", "modifiedDate", "publishDate")
URL_KEYS = ("webSlug", "slug", "url")


def slugify(display_model: str) -> str:
    """'Chevrolet Captiva' -> 'chevrolet-captiva', misma convención que se
    verificó a mano contra Wallapop (es.wallapop.com/coches-segunda-mano/chevrolet-captiva)."""
    text = unicodedata.normalize("NFKD", display_model).encode("ascii", "ignore").decode()
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text


def _first(d: dict, keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _extract_price(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        # formas vistas en otras APIs de Adevinta/Wallapop-like: {"amount": 1234, "currency": "EUR"}
        return _extract_price(_first(value, ("amount", "value", "cash")))
    return None


_HP_PATTERN = re.compile(r"(\d{2,3})\s*cv\b", re.IGNORECASE)


def _hp_from_text(*texts):
    for text in texts:
        if not text:
            continue
        m = _HP_PATTERN.search(text)
        if m:
            return int(m.group(1))
    return None


def _looks_like_item(d: dict) -> bool:
    if not isinstance(d, dict):
        return False
    has_id = any(k in d for k in ID_KEYS)
    has_price = _extract_price(_first(d, PRICE_KEYS)) is not None
    has_title = any(k in d for k in TITLE_KEYS)
    return has_id and has_price and has_title


def _walk_for_items(node, found, max_depth=8, depth=0):
    """Recorre el JSON capturado buscando dicts con pinta de anuncio,
    sin asumir una forma concreta de respuesta (search.objects,
    data.items, section.payload.items... varía según endpoint/versión)."""
    if depth > max_depth:
        return
    if isinstance(node, dict):
        if _looks_like_item(node):
            found.append(node)
            return  # no seguir bajando dentro de un item ya identificado
        for v in node.values():
            _walk_for_items(v, found, max_depth, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _walk_for_items(v, found, max_depth, depth + 1)


def _normalize(item: dict, display_model: str) -> dict:
    source_id = str(_first(item, ID_KEYS))
    title = _first(item, TITLE_KEYS)
    price = _extract_price(_first(item, PRICE_KEYS))
    description = _first(item, DESCRIPTION_KEYS)
    if isinstance(description, dict):
        description = _first(description, ("original", "text"))

    location = _first(item, LOCATION_KEYS)
    city = None
    if isinstance(location, dict):
        city = _first(location, ("city", "title", "name"))
    elif isinstance(location, str):
        city = location

    publish_date = _first(item, DATE_KEYS)

    url_part = _first(item, URL_KEYS)
    url = None
    if url_part:
        url = url_part if url_part.startswith("http") else f"https://es.wallapop.com/item/{url_part}"

    return {
        "source": "wallapop",
        "source_id": source_id,
        "display_model": display_model,
        "make": None,
        "model": None,
        "year": item.get("year"),  # puede no venir en el listado; queda en None si no está
        "price": price,
        "km": item.get("km") or item.get("kilometers"),
        "fuel": item.get("fuel") or item.get("fuelType"),
        "hp": item.get("hp") or item.get("horsePower") or _hp_from_text(title, description),
        "province": city,
        "city": city,
        "seller_type": "professional" if item.get("isProfessional") else "private",
        "has_warranty": bool(item.get("warranty")),
        "description": description,
        "title": title,
        "publish_date": publish_date,
        "url": url,
    }


def fetch_listings(display_model: str, page, max_scroll_rounds: int = 6,
                    scroll_wait_ms: int = 1500, debug_dir: str = None) -> list:
    """page: un playwright.sync_api.Page ya creado (se reutiliza entre
    modelos desde run_wallapop.py para no relanzar el navegador cada vez).

    Estrategia: escuchar las respuestas de red mientras se carga la página
    y se hace scroll (Wallapop pagina por scroll infinito), quedarse con
    las que parezcan JSON de búsqueda, y rebuscar dentro de cada una
    cualquier lista de objetos con pinta de anuncio de coche.
    """
    captured = []

    def on_response(response):
        url = response.url
        if not any(hint in url for hint in API_URL_HINTS):
            return
        ctype = response.headers.get("content-type", "")
        if "json" not in ctype:
            return
        try:
            captured.append({"url": url, "json": response.json()})
        except Exception:
            pass

    page.on("response", on_response)
    try:
        slug = slugify(display_model)
        page.goto(SEARCH_URL.format(slug=slug), timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        stale_rounds = 0
        for _ in range(max_scroll_rounds):
            before = len(captured)
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(scroll_wait_ms)
            if len(captured) == before:
                stale_rounds += 1
                if stale_rounds >= 2:
                    break
            else:
                stale_rounds = 0
    finally:
        page.remove_listener("response", on_response)

    if debug_dir:
        import json
        import os
        os.makedirs(debug_dir, exist_ok=True)
        with open(os.path.join(debug_dir, f"{slugify(display_model)}.json"), "w", encoding="utf-8") as f:
            json.dump(captured, f, ensure_ascii=False, indent=2, default=str)

    items = []
    for resp in captured:
        _walk_for_items(resp["json"], items)

    if not captured:
        raise RuntimeError(
            f"No se capturó ninguna respuesta JSON de Wallapop para {display_model!r} "
            f"(hints buscados: {API_URL_HINTS}). Puede que el sitio use ahora otro dominio/ruta "
            "para su API, o que el bloqueo anti-bot esté sirviendo una página vacía. "
            "Usa scraper/tools/inspect_wallapop.py para ver qué está respondiendo realmente."
        )
    if not items:
        raise RuntimeError(
            f"Se capturaron {len(captured)} respuestas JSON para {display_model!r} pero ninguna "
            "tenía pinta de listado de anuncios (ver ID_KEYS/PRICE_KEYS/TITLE_KEYS en este archivo). "
            f"Revisa el volcado en debug_dir para ajustar el parseo."
        )

    # dedup por id, se queda con la última ocurrencia (más completa si hay varias)
    by_id = {}
    for raw in items:
        norm = _normalize(raw, display_model)
        if norm["source_id"]:
            by_id[norm["source_id"]] = norm
    return list(by_id.values())
