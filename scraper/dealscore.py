"""Cálculo de 'chollos': anuncios activos con precio muy por debajo de lo
esperado para su grupo (mismo modelo vigilado + año), ajustando por
kilometraje cuando hay datos suficientes, y clasificación del anuncio por
estado según palabras clave en título/descripción."""
import statistics
from datetime import datetime, timezone

from . import config

# Mínimo de anuncios con km conocido en el grupo para fiarse de una
# regresión precio~km en vez de comparar directamente contra la mediana.
KM_REGRESSION_MIN_SAMPLES = max(config.CHOLLO_MIN_GROUP_SIZE, 6)

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


def _km_reference_price(rows, median_price):
    """Estima, dentro de un grupo (modelo+año), el precio esperado en
    función del kilometraje mediante una regresión lineal simple
    precio ~ km (el precio baja al subir el km). Si no hay suficientes
    anuncios con km conocido, o la pendiente no tiene sentido (saldría
    más caro cuanto más rodado), se descarta y se usa directamente la
    mediana del grupo -- es una aproximación local sencilla, no un
    modelo de precios real, pero corrige el caso obvio de comparar un
    coche con 300.000 km contra uno con 50.000 km como si fueran
    intercambiables.
    """
    km_rows = [r for r in rows if r["km"] is not None]
    if len(km_rows) < KM_REGRESSION_MIN_SAMPLES:
        return None
    kms = [r["km"] for r in km_rows]
    if len(set(kms)) < 2:
        return None
    try:
        slope, intercept = statistics.linear_regression(kms, [r["price"] for r in km_rows])
    except statistics.StatisticsError:
        return None
    if slope >= 0:  # no tiene sentido: precio subiendo con el km
        return None
    km_min, km_max = min(kms), max(kms)

    def predict(km):
        km_clamped = min(max(km, km_min), km_max)  # sin extrapolar fuera del rango visto
        expected = intercept + slope * km_clamped
        return max(expected, median_price * 0.4)  # cota de seguridad ante grupos pequeños/ruidosos

    return predict


def compute_deals(listings, now: datetime = None):
    """listings: filas de sqlite3.Row (o dicts) de anuncios activos de UN modelo vigilado.

    Devuelve (deals, group_stats) donde deals es la lista de anuncios marcados
    como chollo, con 'discount_ratio', 'group_median' y 'reference_price'
    (el precio contra el que realmente se comparó -- ajustado por km cuando
    fue posible) añadidos.
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
        priced_rows = [r for r in rows if r["price"]]
        if len(priced_rows) < config.CHOLLO_MIN_GROUP_SIZE:
            continue
        prices = [r["price"] for r in priced_rows]
        median_price = statistics.median(prices)
        km_predict = _km_reference_price(priced_rows, median_price)
        group_stats[key] = {"median": median_price, "n": len(priced_rows), "km_adjusted": km_predict is not None}

        for row in priced_rows:
            age_days = days_since(row["publish_date"], now)
            if age_days > config.MAX_AGE_DAYS:
                continue
            price = row["price"]
            reference_price = km_predict(row["km"]) if (km_predict and row["km"] is not None) else median_price
            ratio = price / reference_price
            if ratio <= config.CHOLLO_DISCOUNT_RATIO:
                deal = dict(row)
                deal["discount_ratio"] = ratio
                deal["group_median"] = median_price
                deal["reference_price"] = reference_price
                deal["km_adjusted"] = reference_price != median_price
                deal["age_days"] = age_days
                deal["condition"] = classify_condition(row)
                deals.append(deal)

    deals.sort(key=lambda d: d["discount_ratio"])
    return deals, group_stats
