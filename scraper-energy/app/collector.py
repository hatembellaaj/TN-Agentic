"""
Collecteur GlobalPetrolPrices : récupère + parse + insère en base.

Pour la Phase 1 (carburant) :
- Tunisie essence + Tunisie diesel (pages détail)
- Tableaux mondiaux essence + diesel (countries of interest + stats mondiales)
"""
from __future__ import annotations

import datetime as dt
import logging
import time
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import settings
from app.gpp_client import GPPClient
from app.models import EnergyPrice, EnergyWorldStats, ExchangeRate, ExecutionLog
from app.parser import (
    COUNTRIES_OF_INTEREST,
    TUNISIA_CODE,
    parse_country_detail,
    parse_world_ranking,
)

logger = logging.getLogger(__name__)


# Chemins GPP pour le carburant (Phase 1)
PATHS_FUEL = {
    "carburant_essence": {
        "tunisia": "/Tunisia/gasoline_prices/",
        "world": "/gasoline_prices/",
    },
    "carburant_gasoil": {
        "tunisia": "/Tunisia/diesel_prices/",
        "world": "/diesel_prices/",
    },
}


def _get_latest_usd_tnd_rate(session: Session) -> Decimal | None:
    """Récupère le taux moyen USD→TND le plus récent en base."""
    rate = session.scalar(
        select(ExchangeRate)
        .where(ExchangeRate.devise_code == "USD")
        .order_by(desc(ExchangeRate.date_cotation))
        .limit(1)
    )
    return rate.taux_moyen if rate else None


def _convert_to_tnd(prix_usd: Decimal | None, taux: Decimal | None) -> Decimal | None:
    if prix_usd is None or taux is None:
        return None
    return (Decimal(prix_usd) * Decimal(taux)).quantize(Decimal("0.000001"))


def _log(session, exec_id, step, status, message=None, payload=None, duree_ms=None):
    session.add(ExecutionLog(
        execution_id=exec_id, agent_name="scraper-energy",
        agent_step=step, status=status, message=message,
        duree_ms=duree_ms, payload_json=payload,
    ))
    session.commit()


def collect_fuel(session: Session, execution_id: uuid.UUID | None = None) -> dict[str, Any]:
    """
    Collecte essence + gasoil :
    - Pages Tunisia détail (prix officiel)
    - Tableaux mondiaux (Maghreb + référence + moyenne mondiale + rang Tunisie)
    """
    if execution_id is None:
        execution_id = uuid.uuid4()

    started = time.perf_counter()
    today = dt.date.today()
    now_utc = dt.datetime.now(dt.timezone.utc)
    gpp = GPPClient()

    taux_usd_tnd = _get_latest_usd_tnd_rate(session)
    if taux_usd_tnd is None:
        logger.warning("Taux USD/TND introuvable en base — les prix TND ne seront pas calculés")

    results: dict[str, Any] = {
        "execution_id": str(execution_id),
        "date_collecte": today.isoformat(),
        "taux_usd_tnd": float(taux_usd_tnd) if taux_usd_tnd else None,
        "energy_types": {},
    }
    total_insertions = 0
    errors_list: list[str] = []

    for energy_type, paths in PATHS_FUEL.items():
        type_result = {"countries_inserted": 0, "world_stats_inserted": False, "errors": []}

        # 1) Page mondiale → classement + Maghreb + référence + moyenne + rang Tunisie
        try:
            html_world = gpp.fetch(paths["world"])
            parsed = parse_world_ranking(html_world)
            country_data = parsed["countries"]
            date_src = parsed["date_source"] or today

            # Insertion d'un EnergyPrice par pays d'intérêt
            for country_name, info in country_data.items():
                ep = EnergyPrice(
                    energy_type=energy_type,
                    pays_code=info["code"],
                    pays_nom=country_name,
                    prix_usd=info["price_usd"],
                    prix_tnd=_convert_to_tnd(info["price_usd"], taux_usd_tnd),
                    unite="par_litre",
                    taux_usd_tnd_utilise=taux_usd_tnd,
                    date_donnee_source=date_src,
                    date_collecte=today,
                    source="GlobalPetrolPrices",
                    source_url=f"{settings.GPP_BASE_URL}{paths['world']}",
                    fiabilite="haute",
                    raw_data={
                        "country_name": country_name,
                        "price_usd": str(info["price_usd"]),
                    },
                )
                session.add(ep)
                type_result["countries_inserted"] += 1
                total_insertions += 1

            # Calcul moyenne mondiale à partir des prix du tableau si possible
            # (On la lit depuis la page si présente, sinon on fait la moyenne des
            # countries connus — version simplifiée pour Phase 1)
            prices = [info["price_usd"] for info in country_data.values()]
            moyenne_mondiale = (
                sum(prices) / Decimal(len(prices)) if prices else None
            )
            # Pour la moyenne mondiale RÉELLE, idéalement on parserait la ligne
            # "World" du tableau ; à raffiner en Phase 2 selon HTML réel observé.

            # Cherche le pays le moins cher / le plus cher parmi les pays d'intérêt
            sorted_countries = sorted(country_data.items(), key=lambda x: x[1]["price_usd"])
            min_country = sorted_countries[0] if sorted_countries else None
            max_country = sorted_countries[-1] if sorted_countries else None

            world_stats = EnergyWorldStats(
                energy_type=energy_type,
                moyenne_mondiale_usd=moyenne_mondiale,
                rang_tunisie=parsed.get("rang_tunisie"),
                nombre_pays_classement=parsed.get("total_countries"),
                pays_moins_cher_code=min_country[1]["code"] if min_country else None,
                pays_moins_cher_nom=min_country[0] if min_country else None,
                pays_moins_cher_prix_usd=min_country[1]["price_usd"] if min_country else None,
                pays_plus_cher_code=max_country[1]["code"] if max_country else None,
                pays_plus_cher_nom=max_country[0] if max_country else None,
                pays_plus_cher_prix_usd=max_country[1]["price_usd"] if max_country else None,
                date_donnee_source=date_src,
                date_collecte=today,
                source="GlobalPetrolPrices",
                source_url=f"{settings.GPP_BASE_URL}{paths['world']}",
                raw_data={"countries_count": len(country_data)},
            )
            session.add(world_stats)
            type_result["world_stats_inserted"] = True

        except Exception as exc:  # noqa: BLE001
            logger.exception("Echec collecte mondiale %s", energy_type)
            type_result["errors"].append(f"world: {exc}")
            errors_list.append(f"{energy_type}/world: {exc}")

        # 2) Page Tunisia détail → prix précis avec devise locale + date exacte
        try:
            html_tn = gpp.fetch(paths["tunisia"])
            parsed_tn = parse_country_detail(html_tn, "Tunisia")
            if parsed_tn.get("prix_usd") is not None:
                # Si on a déjà inséré la Tunisie via le tableau mondial avec un
                # prix légèrement différent, on UPSERT en gardant le détail le
                # plus récent. Pour Phase 1 on tolère un doublon : Tunisia
                # apparaît deux fois (tableau mondial + détail), ce qui se
                # diagnostique facilement et permet la traçabilité.
                ep = EnergyPrice(
                    energy_type=energy_type,
                    pays_code=TUNISIA_CODE,
                    pays_nom="Tunisia (page détail)",
                    prix_usd=parsed_tn["prix_usd"],
                    prix_tnd=parsed_tn.get("prix_local"),
                    unite=parsed_tn.get("unite", "par_litre"),
                    taux_usd_tnd_utilise=taux_usd_tnd,
                    date_donnee_source=parsed_tn.get("date_source") or today,
                    date_collecte=today,
                    source="GlobalPetrolPrices",
                    source_url=f"{settings.GPP_BASE_URL}{paths['tunisia']}",
                    fiabilite="haute",
                    raw_data={
                        "devise_locale": parsed_tn.get("devise_locale"),
                        "raw_excerpt": parsed_tn.get("raw_excerpt"),
                    },
                )
                session.add(ep)
                total_insertions += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("Echec collecte Tunisia %s", energy_type)
            type_result["errors"].append(f"tunisia: {exc}")
            errors_list.append(f"{energy_type}/tunisia: {exc}")

        results["energy_types"][energy_type] = type_result

    session.commit()

    duree_ms = int((time.perf_counter() - started) * 1000)
    _log(
        session, execution_id, "collect_fuel",
        "success" if not errors_list else "partial",
        message=f"{total_insertions} insertions, {len(errors_list)} erreurs",
        duree_ms=duree_ms,
        payload={"errors": errors_list[:10], "total_insertions": total_insertions},
    )

    results["status"] = "success" if not errors_list else "partial"
    results["total_insertions"] = total_insertions
    results["duree_ms"] = duree_ms
    results["errors"] = errors_list[:20]
    return results
