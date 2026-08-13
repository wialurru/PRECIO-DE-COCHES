"""Cálculo de 'chollos': anuncios activos con precio muy por debajo de la
mediana de su grupo (mismo modelo vigilado + año), y clasificación del
anuncio por estado según palabras clave en título/descripción."""
import statistics
from datetime import datetime, timezone

from . import config

CONDITION_RULES = [
    # (etiqueta, palabras clave en minúsculas)
    ("Para piezas / no arranca / accidentado",
     ["para piezas", "no arranca", "accidentado", "siniestro", "averiado", "no funciona"]),
    ("Necesita reparación / revisión pendiente",
     ["a reparar", "necesita", "pendiente de", "avería", "fallo motor", "urge vender"]),
    ("Buen estado / revisado / con garantía",
     ["buen estado", "revisado", "garantía", "garantia", "recién pasada", "itv reciente",
      "mantenimientos al día", "perfecto estado", "impecable", "como nuevo"]),
]


def classify_condition(listing) -> str:
    text = " ".join(filter(None, [listing["title"], listing["description"]])).lower()
    for label, keywords in CONDITION_RULES:
        if any(kw in text for kw in keywords):
            return label
    return "Estado no especificado por el vendedor"


def days_since(publish_date_iso: str, now: datetime) -> float:
    if not publish_date_iso:
        return float("inf")
    try:
        dt = datetime.fromisoformat(publish_date_iso.replace("Z", "+00:00"))
    except ValueError:
        return float("inf")
    return (now - dt).total_seconds() / 86400.0


def compute_deals(listings, now: datetime = None):
    """listings: filas de sqlite3.Row (o dicts) de anuncios activos de UN modelo vigilado.

    Devuelve (deals, group_stats) donde deals es la lista de anuncios marcados
    como chollo, con 'discount_ratio' y 'group_median' añadidos.
    """
    now = now or datetime.now(timezone.utc)

    groups = {}
    for row in listings:
        year = row["year"]
        price = row["price"]
        if not price or price < config.CHOLLO_MIN_PRICE_EUR:
            continue
        key = year if year else "sin_año"
        groups.setdefault(key, []).append(row)

    deals = []
    group_stats = {}
    for key, rows in groups.items():
        prices = [r["price"] for r in rows if r["price"]]
        if len(prices) < config.CHOLLO_MIN_GROUP_SIZE:
            continue
        median_price = statistics.median(prices)
        group_stats[key] = {"median": median_price, "n": len(prices)}
        for row in rows:
            price = row["price"]
            if not price:
                continue
            ratio = price / median_price
            age_days = days_since(row["publish_date"], now)
            if ratio <= config.CHOLLO_DISCOUNT_RATIO and age_days <= config.MAX_AGE_DAYS:
                deal = dict(row)
                deal["discount_ratio"] = ratio
                deal["group_median"] = median_price
                deal["age_days"] = age_days
                deal["condition"] = classify_condition(row)
                deals.append(deal)

    deals.sort(key=lambda d: d["discount_ratio"])
    return deals, group_stats
