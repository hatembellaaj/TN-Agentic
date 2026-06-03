"""
Parseur HTML pour GlobalPetrolPrices.

Deux structures de page à gérer :

1. Page pays détail (ex. /Tunisia/gasoline_prices/) :
   - Le prix principal apparaît dans un encart avec la valeur en USD et la
     devise locale.
   - Texte type : "Tunisia Gasoline prices, liter, 25-May-2026" ou similaire.
   - Le prix est typiquement dans un <td> avec class "regularxl" ou un <p>
     contenant le chiffre + "$" ou "USD".

2. Page mondiale (ex. /gasoline_prices/) :
   - Tableau avec une ligne par pays.
   - Colonnes : Country | Pricing (en USD).
   - Trié par défaut du plus cher au moins cher.

L'extraction est volontairement souple : on cherche des patterns de prix
"X.XXX" suivis ou précédés de "$" / "USD", et des noms de pays connus.
"""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from bs4 import BeautifulSoup


# Mapping pays utilisés dans les articles (Maghreb + référence diaspora)
COUNTRIES_OF_INTEREST: dict[str, str] = {
    "Tunisia": "TN",
    "Algeria": "DZ",
    "Morocco": "MA",
    "Libya": "LY",
    "France": "FR",
    "Italy": "IT",
    "Germany": "DE",
}

# Code ISO pour la Tunisie (référence centrale)
TUNISIA_CODE = "TN"


_PRICE_RE = re.compile(r"(\d+[.,]\d+|\d+)")
_DATE_RE = re.compile(r"(\d{1,2})[-\s](\w{3,9})[-\s](\d{4})", re.IGNORECASE)

_MONTHS_EN = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def _to_decimal(text: str) -> Decimal | None:
    if not text:
        return None
    s = text.strip().replace(",", ".")
    m = _PRICE_RE.search(s)
    if not m:
        return None
    try:
        return Decimal(m.group(1).replace(",", "."))
    except InvalidOperation:
        return None


def _parse_date_en(text: str) -> dt.date | None:
    """Parse '25-May-2026' ou '25 May 2026' ou variations."""
    m = _DATE_RE.search(text or "")
    if not m:
        return None
    day = int(m.group(1))
    month_name = m.group(2).lower()[:9]
    year = int(m.group(3))
    month = _MONTHS_EN.get(month_name) or _MONTHS_EN.get(month_name[:3])
    if not month:
        return None
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


# ============================================================
# Parser : page pays détail (ex. /Tunisia/gasoline_prices/)
# ============================================================

def parse_country_detail(html: str, pays_attendu: str = "Tunisia") -> dict[str, Any]:
    """
    Extrait le prix le plus récent affiché sur la page pays.

    Renvoie : { prix_usd: Decimal, prix_local: Decimal | None, devise_locale: str | None,
                date_source: date | None, unite: str, raw_excerpt: str }
    """
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    # Date de mise à jour
    date_source = _parse_date_en(text)

    # Détection unité
    unite = "par_litre"
    if "kWh" in text or "kwh" in text:
        unite = "par_kwh"

    # Le prix en USD apparaît typiquement dans le premier paragraphe résumé
    # "Tunisia Gasoline prices: We show prices for Tunisia from ... to ...
    # The average price during that period was 2.55 (Tunisian Dinar) with a
    # minimum of ... For comparison, the average price of gasoline in the
    # world for this period is 6.66."
    # OU dans un encart "Tunisia: The price of octane-95 gasoline is 0.88 USD"
    prix_usd: Decimal | None = None
    prix_local: Decimal | None = None
    devise_locale: str | None = None

    # Pattern 1 : "X.XX U.S. Dollar" ou "X.XX USD"
    m = re.search(r"(\d+[.,]\d+)\s*(?:U\.?S\.?\s*Dollar|USD)", text, re.IGNORECASE)
    if m:
        prix_usd = _to_decimal(m.group(1))

    # Pattern 2 : "X.XX (Tunisian Dinar)" → prix local
    m = re.search(
        r"(\d+[.,]\d+)\s*\(?\s*(Tunisian Dinar|TND|Algerian Dinar|DZD|"
        r"Moroccan Dirham|MAD|Libyan Dinar|LYD|Euro|EUR)\)?",
        text,
        re.IGNORECASE,
    )
    if m:
        prix_local = _to_decimal(m.group(1))
        devise_locale = m.group(2)

    raw_excerpt = text[:500]
    return {
        "prix_usd": prix_usd,
        "prix_local": prix_local,
        "devise_locale": devise_locale,
        "date_source": date_source,
        "unite": unite,
        "raw_excerpt": raw_excerpt,
    }


# ============================================================
# Parser : tableau mondial (ex. /gasoline_prices/)
# ============================================================

def parse_world_ranking(html: str) -> dict[str, Any]:
    """
    Extrait le tableau de classement mondial.

    Renvoie : {
        countries: { 'Country Name': { 'price_usd': Decimal, 'rank': int } },
        date_source: date | None,
        total_countries: int
    }
    """
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    date_source = _parse_date_en(text)

    countries: dict[str, dict[str, Any]] = {}

    # Stratégie : on cherche TOUS les <td> ou <tr> qui contiennent
    # un nom de pays connu + un prix décimal proche.
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        cells_text = [td.get_text(strip=True) for td in tds]
        # Cherche le pays
        country_name = None
        for cell in cells_text:
            cell_lower = cell.lower().strip()
            for known in COUNTRIES_OF_INTEREST:
                if known.lower() == cell_lower or known.lower() in cell_lower.split():
                    country_name = known
                    break
            if country_name:
                break

        if not country_name:
            continue

        # Cherche le prix (premier décimal qui ressemble à 0.XX-9.XX)
        prix: Decimal | None = None
        for cell in cells_text:
            val = _to_decimal(cell)
            if val is not None and Decimal("0.001") < val < Decimal("50"):
                prix = val
                break

        if prix is None:
            continue

        countries[country_name] = {
            "code": COUNTRIES_OF_INTEREST[country_name],
            "price_usd": prix,
        }

    # Compte le nombre total de lignes du tableau (utile pour le rang)
    # On essaie de trouver le tableau principal et compter ses <tr>.
    main_table = None
    for tbl in soup.find_all("table"):
        rows = tbl.find_all("tr")
        if len(rows) > 30:  # vraisemblablement le grand tableau pays
            main_table = tbl
            break
    total_countries = len(main_table.find_all("tr")) if main_table else 0

    # Détermine le rang Tunisie : on cherche son ordre dans le tableau principal
    rang_tunisie = None
    if main_table:
        for idx, tr in enumerate(main_table.find_all("tr"), start=1):
            if "Tunisia" in tr.get_text():
                rang_tunisie = idx
                break

    return {
        "countries": countries,
        "date_source": date_source,
        "total_countries": total_countries,
        "rang_tunisie": rang_tunisie,
    }
