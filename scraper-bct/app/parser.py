"""
Parseur du HTML de https://www.bct.gov.tn/bct/siteprod/index.jsp.

Deux blocs extraits :
1. "COURS MOYENS DES DEVISES DD/MM/YYYY" → 7 devises (CAD, USD, GBP, JPY, MAD, EUR, LYD)
2. "Principaux Indicateurs" → TM, taux directeur, TMM, Compte Trésor,
   Avoirs nets MDT + jours d'importation, Billets et monnaies, Refinancement.
"""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from bs4 import BeautifulSoup, Tag


# ============================================================
# DEVISES
# ============================================================

_DEVISE_ALT_RE = re.compile(r"^([A-Z]{3})/CHF", re.IGNORECASE)
_DATE_FR_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


def _to_decimal_fr(text: str) -> Decimal | None:
    """Convertit '3,3907' / '1 234,56' en Decimal('3.3907') / Decimal('1234.56')."""
    if text is None:
        return None
    cleaned = text.strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _to_int_fr(text: str) -> int | None:
    if text is None:
        return None
    cleaned = text.strip().replace("\xa0", "").replace(" ", "").replace(",", "")
    try:
        return int(cleaned)
    except ValueError:
        # Peut être un float du genre "1.0"
        try:
            return int(float(cleaned))
        except ValueError:
            return None


def _parse_date_fr(text: str) -> dt.date | None:
    m = _DATE_FR_RE.search(text or "")
    if not m:
        return None
    d, mo, y = m.group(1, 2, 3)
    try:
        return dt.date(int(y), int(mo), int(d))
    except ValueError:
        return None


def parse_devises(html: str) -> tuple[list[dict[str, Any]], dt.date | None]:
    """
    Renvoie (liste devises, date_cotation).

    Chaque devise est un dict avec : code, unite, valeur_brute, taux_moyen_pour_1, raw_html.
    Le `taux_moyen_pour_1` est normalisé à 1 unité de la devise étrangère (utile pour comparer
    JPY à EUR : on stocke partout "1 X = N TND").
    """
    soup = BeautifulSoup(html, "lxml")

    # Trouve le titre du bloc devises
    h3 = soup.find(
        "h3",
        string=lambda t: t and "COURS MOYENS DES DEVISES" in t.upper(),
    )
    date_cotation: dt.date | None = None
    if h3:
        date_cotation = _parse_date_fr(h3.get_text())

    # Le conteneur est le <div class="content flags"> qui suit le h3
    container = None
    if h3:
        container = h3.find_next("div", class_="content flags")
    if container is None:
        # Fallback : on cherche tout div qui contient un <img alt='*/CHF'>
        for div in soup.find_all("div", class_="content"):
            if div.find("img", alt=_DEVISE_ALT_RE):
                container = div
                break

    devises: list[dict[str, Any]] = []
    if container is None:
        return devises, date_cotation

    # Chaque devise est un <div> direct contenant un <img alt='XXX/CHF'>
    for div in container.find_all("div"):
        img = div.find("img", alt=_DEVISE_ALT_RE)
        if not img:
            continue
        # Évite les doubles : on prend seulement les divs qui sont des "lignes" complètes
        if img.parent and img.parent.name != "div":
            continue
        m = _DEVISE_ALT_RE.match(img.get("alt", ""))
        if not m:
            continue
        code = m.group(1).upper()
        # Récupère les deux <b> de la ligne dans l'ordre (unité, valeur)
        bolds = div.find_all("b")
        if len(bolds) < 2:
            continue
        unite = _to_int_fr(bolds[0].get_text())
        valeur_brute = _to_decimal_fr(bolds[1].get_text())
        if unite is None or valeur_brute is None or unite == 0:
            continue
        taux_par_1 = (valeur_brute / Decimal(unite)).quantize(Decimal("0.000001"))
        devises.append(
            {
                "code": code,
                "unite": unite,
                "valeur_brute": valeur_brute,
                "taux_moyen_pour_1": taux_par_1,
                "raw_html": str(div)[:1000],
            }
        )

    # Dé-doublonne par code (au cas où la page change)
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for d in devises:
        if d["code"] in seen:
            continue
        seen.add(d["code"])
        deduped.append(d)
    return deduped, date_cotation


# ============================================================
# INDICATEURS MACRO
# ============================================================

# Patterns "label → indicateur_type, unite, regex"
# Note : on opère sur le texte décodé (BS4 résout déjà &eacute; etc.).
_INDICATOR_PATTERNS: list[dict[str, Any]] = [
    {
        "type": "TM",
        "unite": "%",
        "regex": re.compile(
            r"Taux du marché monétaire\s*\(TM\)\s*au\s+(\d{2}/\d{2}/\d{4})\s*:\s*([\d ,.]+)\s*%",
            re.IGNORECASE,
        ),
    },
    {
        "type": "taux_directeur",
        "unite": "%",
        "regex": re.compile(
            r"Taux d'intérêt directeur\s*au\s+(\d{2}/\d{2}/\d{4})\s*:\s*([\d ,.]+)\s*%",
            re.IGNORECASE,
        ),
    },
    {
        "type": "TMM",
        "unite": "%",
        "regex": re.compile(
            r"Taux moyen du marché monétaire\s*\(TMM\)\s*du mois d'?([\wéûôîè ]+\d{4})\s*:\s*([\d ,.]+)\s*%",
            re.IGNORECASE,
        ),
        # Ce pattern renvoie (période_textuelle, valeur) au lieu de (date, valeur)
        "is_monthly": True,
    },
    {
        "type": "TRE",
        "unite": "%",
        "regex": re.compile(
            r"Taux de rémunération de l'épargne\s*\(TRE\)\s*du mois de\s+([\wéûôîè ]+\d{4})\s*:\s*([\d ,.]+)\s*%",
            re.IGNORECASE,
        ),
        "is_monthly": True,
    },
    {
        "type": "compte_tresor",
        "unite": "MDT",
        "regex": re.compile(
            r"Compte courant du Trésor\s*au\s+(\d{2}/\d{2}/\d{4})\s*:\s*([\d ,.]+)\s*MDT",
            re.IGNORECASE,
        ),
    },
    {
        "type": "avoirs_nets_mdt",
        "unite": "MDT",
        "regex": re.compile(
            r"Avoirs nets en devises\s*au\s+(\d{2}/\d{2}/\d{4}).*?en MDT\s*:?\s*([\d ,.]+)",
            re.IGNORECASE | re.DOTALL,
        ),
    },
    {
        "type": "avoirs_nets_jours_import",
        "unite": "jours",
        "regex": re.compile(
            r"Avoirs nets en devises\s*au\s+(\d{2}/\d{2}/\d{4}).*?en jours d'importation\s*:?\s*([\d ,.]+)",
            re.IGNORECASE | re.DOTALL,
        ),
    },
    {
        "type": "billets_circulation",
        "unite": "MDT",
        "regex": re.compile(
            r"Billets et monnaies en circulation\s*au\s+(\d{2}/\d{2}/\d{4})\s*:?\s*([\d ,.]+)\s*MDT",
            re.IGNORECASE,
        ),
    },
    {
        "type": "refinancement",
        "unite": "MDT",
        "regex": re.compile(
            r"Volume global de refinancement\s*au\s+(\d{2}/\d{2}/\d{4})\s*:\s*([\d ,.]+)\s*MDT",
            re.IGNORECASE,
        ),
    },
]


def parse_indicators(html: str) -> list[dict[str, Any]]:
    """
    Renvoie une liste de dicts : type, valeur, unite, date_cotation (date ou None),
    periode_str (pour les indicateurs mensuels), raw_snippet.
    """
    soup = BeautifulSoup(html, "lxml")
    # On opère sur le texte décodé global pour éviter les entités HTML brutes
    page_text = soup.get_text(" ", strip=True)
    # Nettoyage des espaces multiples
    page_text = re.sub(r"\s+", " ", page_text)

    results: list[dict[str, Any]] = []
    for pat in _INDICATOR_PATTERNS:
        m = pat["regex"].search(page_text)
        if not m:
            continue
        date_or_period, value_str = m.group(1), m.group(2)
        valeur = _to_decimal_fr(value_str)
        if valeur is None:
            continue

        if pat.get("is_monthly"):
            date_obj = None
            periode_str = date_or_period.strip()
        else:
            date_obj = _parse_date_fr(date_or_period)
            periode_str = None

        results.append(
            {
                "type": pat["type"],
                "valeur": valeur,
                "unite": pat["unite"],
                "date_cotation": date_obj,
                "periode_str": periode_str,
                "raw_snippet": m.group(0)[:300],
            }
        )
    return results


# ============================================================
# Helper haut niveau : tout en un appel
# ============================================================

def parse_bct_index(html: str) -> dict[str, Any]:
    """Parse en une fois devises + indicateurs depuis index.jsp."""
    devises, date_cotation = parse_devises(html)
    indicators = parse_indicators(html)
    return {
        "date_cotation": date_cotation,
        "devises": devises,
        "indicators": indicators,
    }


# ============================================================
# PARSEUR indicateurs.jsp — 11 sections (Sprint 3)
# ============================================================

# Mapping numéro de section romain → (entier, indicateur_type, unité)
# Les types choisis sont distincts de ceux d'index.jsp pour éviter les doublons
# quand les deux sources sont collectées ensemble. Les chevauchements (I=compte_tresor,
# III=billets_circulation, IX=avoirs_nets) sont stockés avec suffixe "_detail".
_SECTION_MAPPING: dict[int, dict[str, str]] = {
    1:  {"type": "compte_tresor_detail",       "unite": "MDT",    "label": "Solde du compte courant du Trésor"},
    2:  {"type": "solde_banques",              "unite": "MDT",    "label": "Solde du compte courant ordinaire des banques"},
    3:  {"type": "billets_circulation_detail", "unite": "MDT",    "label": "Billets et monnaies en circulation"},
    4:  {"type": "marche_monetaire",           "unite": "MDT",    "label": "Marché monétaire"},
    5:  {"type": "bons_tresor",                "unite": "MDT",    "label": "Bons du Trésor"},
    6:  {"type": "recettes_touristiques",      "unite": "MDT",    "label": "Recettes touristiques cumulées"},
    7:  {"type": "revenus_travail_diaspora",   "unite": "MDT",    "label": "Revenus du travail (diaspora) cumulés"},
    8:  {"type": "service_dette_exterieure",   "unite": "MDT",    "label": "Service de la dette extérieure cumulés"},
    9:  {"type": "avoirs_nets_devises_detail", "unite": "MDT",    "label": "Avoirs nets en devises BCT"},
    10: {"type": "taux_change_interbancaires", "unite": "TND",    "label": "Taux de change interbancaires"},
    11: {"type": "indice_tunindex",            "unite": "points", "label": "Indice boursier TUNINDEX"},
}


_DATE_DDMM_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})\s*$")


def _parse_ddmm_with_current_year(text: str, fallback_today: dt.date | None = None) -> dt.date | None:
    """
    indicateurs.jsp affiche les dates au format DD/MM sans année.
    On suppose l'année courante (avec heuristique pour le passage à l'an précédent
    si la date est dans le futur de plus de 30 jours).
    """
    if not text:
        return None
    m = _DATE_DDMM_RE.match(text.strip())
    if not m:
        return None
    d, mo = int(m.group(1)), int(m.group(2))
    today = fallback_today or dt.date.today()
    try:
        candidate = dt.date(today.year, mo, d)
    except ValueError:
        return None
    # Heuristique : si la date "candidate" est dans plus de 30j dans le futur,
    # c'est probablement l'année dernière (rare mais possible début janvier).
    if (candidate - today).days > 30:
        candidate = candidate.replace(year=today.year - 1)
    return candidate


_BCT_MOD_CONTENT_CLASS_RE = re.compile(r"bct-mod-content-(\d+)")


# ============================================================
# PARSEUR cours_archiv.jsp — historique (backfill)
# ============================================================

# Capture une devise sur 3 lettres majuscules (DZD, EUR, USD, etc.)
_DEVISE_CODE_RE = re.compile(r"\b([A-Z]{3})\b")

# Liste des codes devises connus de la BCT pour limiter le bruit
_KNOWN_DEVISE_CODES = {
    "DZD", "SAR", "CAD", "DKK", "USD", "GBP", "JPY", "MAD", "NOK", "SEK",
    "CHF", "KWD", "AED", "EUR", "LYD", "MRU", "BHD", "QAR", "CNY", "OMR",
    "TRY", "RUB", "JOD", "ZAR",
}


def parse_archive_page(html: str) -> tuple[list[dict[str, Any]], dt.date | None]:
    """
    Parse la réponse HTML de cours_archiv.jsp pour une date donnée.

    Structure observée :
      - Un en-tête contenant "Journée du DD/MM/AAAA"
      - Un tableau « cours moyens des devises cotées » (interbancaires) avec
        20 devises : drapeau, nom, sigle, unité, valeur
      - Un second tableau « cours moyens en dinar tunisien pour le change manuel »
        (taux touriste) — on ignore pour le POC.

    Renvoie (liste_devises, date_cotation).
    """
    soup = BeautifulSoup(html, "lxml")

    # Date depuis "Journée du DD/MM/AAAA"
    date_cotation: dt.date | None = None
    page_text = soup.get_text(" ", strip=True)
    m = re.search(r"Journ[ée]e du\s+(\d{1,2})/(\d{1,2})/(\d{4})", page_text)
    if m:
        try:
            date_cotation = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            date_cotation = None

    # On parcourt tous les <tr> et on cherche ceux qui contiennent un code devise
    # de la liste connue + une unité (int) + une valeur (décimal).
    devises: list[dict[str, Any]] = []
    seen: set[str] = set()

    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        cells_text = [td.get_text(strip=True) for td in tds]

        # Trouve un code devise connu dans une cellule
        code: str | None = None
        for txt in cells_text:
            mcode = _DEVISE_CODE_RE.search(txt)
            if mcode and mcode.group(1) in _KNOWN_DEVISE_CODES:
                code = mcode.group(1)
                break
        if not code or code in seen:
            continue

        # Cherche unité (entier "petit") et valeur (décimal) parmi les cellules
        unite: int | None = None
        valeur: Decimal | None = None
        for txt in cells_text:
            if not txt:
                continue
            # Essai entier (1, 10, 100, 1000)
            if unite is None:
                try:
                    candidate = int(txt.replace(" ", ""))
                    if candidate in (1, 10, 100, 1000):
                        unite = candidate
                        continue
                except ValueError:
                    pass
            # Essai décimal (valeur cotation)
            if valeur is None:
                val = _to_decimal_fr(txt)
                if val is not None and val > 0 and val != Decimal(unite or 0):
                    valeur = val

        if unite is None or valeur is None or unite == 0:
            continue

        taux_par_1 = (valeur / Decimal(unite)).quantize(Decimal("0.000001"))
        devises.append({
            "code": code,
            "unite": unite,
            "valeur_brute": valeur,
            "taux_moyen_pour_1": taux_par_1,
            "raw_html": str(tr)[:500],
        })
        seen.add(code)

    return devises, date_cotation


# ============================================================
# PARSEUR indicateurs.jsp — anciennement (Sprint 3)
# ============================================================

def parse_indicators_page(html: str) -> list[dict[str, Any]]:
    """
    Parse https://www.bct.gov.tn/bct/siteprod/indicateurs.jsp.

    Renvoie une liste de dicts, un par section :
        {
            "section_id": 6,
            "type": "recettes_touristiques",
            "label": "Recettes touristiques cumulées",
            "unite": "MDT",
            "date_cotation": date(2026, 5, 10) | None,
            "row_label": "Indice TUNINDEX(base 1000...)" | None,
            "valeur_principale": Decimal("2224.2") | None,
            "valeurs_brutes": [Decimal, Decimal, ...],
            "raw_snippet": "..."
        }
    """
    soup = BeautifulSoup(html, "lxml")
    today = dt.date.today()

    results: list[dict[str, Any]] = []

    # On itère sur tous les tbody.bct-mod-content-N
    for tbody in soup.find_all("tbody", class_=_BCT_MOD_CONTENT_CLASS_RE):
        cls_attr = tbody.get("class") or []
        # Récupère le numéro de section depuis la classe
        section_id = None
        for c in cls_attr:
            m = _BCT_MOD_CONTENT_CLASS_RE.search(c)
            if m:
                section_id = int(m.group(1))
                break
        if section_id is None:
            continue

        mapping = _SECTION_MAPPING.get(section_id)
        if mapping is None:
            # Section non mappée : on l'ignore (ou on pourrait la stocker en générique)
            continue

        # Pour chaque <tr> dans le tbody (en général un seul, parfois plus)
        rows = tbody.find_all("tr")
        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue

            # Convention observée :
            #   td[0] = label (souvent vide, parfois "Indice TUNINDEX...")
            #   td[1] = date au format DD/MM (souvent vide)
            #   td[2..N] = valeurs numériques
            row_label = tds[0].get_text(strip=True) or None
            date_text = tds[1].get_text(strip=True)
            date_cotation = _parse_ddmm_with_current_year(date_text, fallback_today=today)

            valeurs_brutes: list[Decimal] = []
            for td in tds[2:]:
                val = _to_decimal_fr(td.get_text(strip=True))
                if val is not None:
                    valeurs_brutes.append(val)

            valeur_principale = valeurs_brutes[0] if valeurs_brutes else None

            # Si toute la ligne est vide (ex : XI un jour sans cotation), on saute
            if valeur_principale is None and not valeurs_brutes and not row_label:
                continue

            results.append(
                {
                    "section_id": section_id,
                    "type": mapping["type"],
                    "label": mapping["label"],
                    "unite": mapping["unite"],
                    "date_cotation": date_cotation,
                    "row_label": row_label,
                    "valeur_principale": valeur_principale,
                    "valeurs_brutes": [str(v) for v in valeurs_brutes],
                    "raw_snippet": str(tr)[:600],
                }
            )

    return results
