"""Configuración: top de modelos a vigilar y parámetros de scraping.

Cada modelo lleva los identificadores necesarios para las dos fuentes:
- coches.net usa IDs numéricos internos (make_id / model_id), no slugs de texto.
  Se han resuelto consultando el catálogo que coches.net incrusta en sus propias
  páginas (listFiltersOptions.vehicles), no son inventados.
- Milanuncios usa slugs de texto tipo "marca-modelo-de-segunda-mano", verificados
  uno a uno contra el sitio real.

Añadir un modelo nuevo: buscar su make_id/model_id en coches.net (ver
scraper/tools/lookup_coches_net_ids.py) y comprobar el slug de Milanuncios
visitando https://www.milanuncios.com/<marca>-<modelo>-de-segunda-mano/
"""

# (nombre_mostrado, coches_net_make_id, coches_net_model_id, milanuncios_make_slug, milanuncios_model_slug)
# IDs de coches.net resueltos contra el catálogo real que la propia web expone en
# listFiltersOptions (no inventados). Slugs de Milanuncios verificados uno a uno.
TOP_MODELS = [
    ("Volkswagen Golf", 47, 89, "volkswagen", "golf"),
    ("Volkswagen Polo", 47, 109, "volkswagen", "polo"),
    ("Volkswagen Tiguan", 47, 628, "volkswagen", "tiguan"),
    # T-Roc no tiene página propia en Milanuncios (404): se vigila solo en coches.net
    ("Volkswagen T-Roc", 47, 1232, None, None),
    ("Seat Leon", 39, 410, "seat", "leon"),
    ("Seat Ibiza", 39, 2, "seat", "ibiza"),
    # Arona no tiene página propia en Milanuncios (404): se vigila solo en coches.net
    ("Seat Arona", 39, 1231, None, None),
    ("Opel Corsa", 32, 77, "opel", "corsa"),
    ("Opel Astra", 32, 67, "opel", "astra"),
    ("Opel Mokka", 32, 1036, "opel", "mokka"),
    ("Peugeot 208", 33, 1021, "peugeot", "208"),
    ("Peugeot 308", 33, 447, "peugeot", "308"),
    ("Peugeot 2008", 33, 1077, "peugeot", "2008"),
    ("Peugeot 3008", 33, 934, "peugeot", "3008"),
    ("Renault Clio", 35, 90, "renault", "clio"),
    ("Renault Megane", 35, 17, "renault", "megane"),
    ("Renault Captur", 35, 1069, "renault", "captur"),
    ("Citroen C3", 11, 485, "citroen", "c3"),
    ("Citroen C4", 11, 353, "citroen", "c4"),
    ("Toyota Yaris", 46, 322, "toyota", "yaris"),
    ("Toyota Corolla", 46, 272, "toyota", "corolla"),
    # C-HR no tiene página propia en Milanuncios (404): se vigila solo en coches.net
    ("Toyota C-HR", 46, 1211, None, None),
    ("Toyota RAV4", 46, 131, "toyota", "rav4"),
    ("Nissan Qashqai", 31, 606, "nissan", "qashqai"),
    ("Nissan X-Trail", 31, 455, "nissan", "x-trail"),
    ("Nissan Juke", 31, 976, "nissan", "juke"),
    ("Hyundai i20", 18, 928, "hyundai", "i20"),
    ("Hyundai i30", 18, 622, "hyundai", "i30"),
    ("Hyundai Tucson", 18, 529, "hyundai", "tucson"),
    ("Kia Sportage", 22, 139, "kia", "sportage"),
    ("Kia Ceed", 22, 607, "kia", "ceed"),
    # Niro no tiene página propia en Milanuncios (404): se vigila solo en coches.net
    ("Kia Niro", 22, 1197, None, None),
    ("Audi A3", 4, 345, "audi", "a3"),
    ("BMW Serie 1", 7, 539, "bmw", "serie-1"),
    ("Mercedes-Benz Clase A", 28, 275, "mercedes-benz", "clase-a"),
    ("Ford Fiesta", 15, 86, "ford", "fiesta"),
    ("Ford Focus", 15, 38, "ford", "focus"),
    ("Skoda Octavia", 40, 350, "skoda", "octavia"),
    ("Dacia Sandero", 1011, 903, "dacia", "sandero"),
    ("Dacia Duster", 1011, 962, "dacia", "duster"),
]

# Modelos extra fuera del "top 40" pero de interés propio del usuario
EXTRA_MODELS = [
    ("Chevrolet Captiva", 9, 592, "chevrolet", "captiva"),
]

ALL_MODELS = TOP_MODELS + EXTRA_MODELS

# Cuántas páginas de resultados pedir por modelo y fuente en cada pasada.
# coches.net: ~35 anuncios/página. Milanuncios: ~41 anuncios/página.
MAX_PAGES_PER_SOURCE = 2

# Antigüedad máxima (días) para considerar un anuncio "reciente"
MAX_AGE_DAYS = 15

# Pausa entre peticiones HTTP (segundos) para no saturar los servidores.
# Se aplica con jitter aleatorio: REQUEST_DELAY_SECONDS +/- REQUEST_DELAY_JITTER
REQUEST_DELAY_SECONDS = 1.5
REQUEST_DELAY_JITTER = 0.6

# Reintentos por fuente si la petición falla (403, timeout, bloqueo anti-bot,
# típico en runners de GitHub Actions cuyas IPs a veces están en listas
# negras de estos sitios) antes de darla por perdida en este barrido.
MAX_RETRIES_PER_SOURCE = 2
RETRY_BACKOFF_SECONDS = 6

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

DB_PATH = "data/precios.db"
CHOLLOS_MD_PATH = "chollos/latest.md"
CHOLLOS_JSON_PATH = "chollos/latest.json"

# Umbral de descuento sobre la mediana del grupo (marca+modelo+año) para
# considerar un anuncio "chollo"
CHOLLO_DISCOUNT_RATIO = 0.75  # precio <= 75% de la mediana del grupo
CHOLLO_MIN_GROUP_SIZE = 4     # mínimo de anuncios en el grupo para fiarse de la mediana
CHOLLO_MIN_PRICE_EUR = 800    # por debajo de esto, casi seguro error/pieza/estafa: se descarta

# Presupuesto máximo real del usuario. El informe destaca aparte, arriba de
# todo, los chollos que entran dentro de esto -- no tiene sentido enseñar en
# primer plano un BMW Serie 1 rebajado a 12.000€ si el límite son 5.000€.
USER_MAX_BUDGET_EUR = 5000

# Provincias que quedan totalmente fuera del escáner (nunca se guardan en
# BD): el usuario no quiere anuncios de las islas por el coste/logística de
# traer el coche a la península. Nombres tal cual los devuelven coches.net
# y Milanuncios (ver `province` en scraper/db.py).
EXCLUDED_PROVINCES = {"Baleares", "Las Palmas", "Sta. C. Tenerife", "Tenerife"}

# El usuario vive en Cataluña: el informe destaca primero los chollos de
# estas provincias (dentro de presupuesto), sin descartar el resto de
# España -- a diferencia de las islas, esto es una preferencia, no una
# exclusión.
USER_PRIORITY_PROVINCES = {"Barcelona", "Girona", "Lleida", "Tarragona"}
