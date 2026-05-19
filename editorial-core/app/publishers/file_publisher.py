"""
FilePublisher : écrit les articles en fichiers HTML + sidecar JSON Yoast sur disque.
Sortie consommée par Nginx (servie en lecture) et par le dashboard.

Layout :
    /var/www/articles/AAAA/MM/JJ/{theme}-{langue}.html
    /var/www/articles/AAAA/MM/JJ/{theme}-{langue}.meta.json
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any

from app.config import settings
from app.publishers.base import Publisher, PublishResult

logger = logging.getLogger(__name__)


HTML_WRAPPER = """<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{titre}</title>
  <meta name="description" content="{meta_desc}">
  <meta name="keywords" content="{keywords}">
  <style>
    body {{ font-family: Georgia, serif; max-width: 760px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; color: #222; }}
    h1 {{ font-size: 1.8rem; border-bottom: 2px solid #2c5282; padding-bottom: 0.4rem; }}
    h2 {{ color: #2c5282; margin-top: 2rem; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.95rem; }}
    th, td {{ padding: 0.5rem 0.75rem; border: 1px solid #ccc; text-align: left; }}
    th {{ background: #f0f4f8; }}
    .meta {{ color: #888; font-size: 0.85rem; margin-bottom: 1.5rem; }}
  </style>
</head>
<body>
  <h1>{titre}</h1>
  <p class="meta">Aperçu généré par TN-Agentic — {date_iso}</p>
  {contenu}
</body>
</html>
"""


class FilePublisher(Publisher):
    backend_name = "file"

    def __init__(self, base_dir: str | None = None):
        self.base_dir = Path(base_dir or settings.ARTICLES_OUTPUT_DIR)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _target_dir(self, date_publication: dt.date) -> Path:
        d = self.base_dir / f"{date_publication.year:04d}" / f"{date_publication.month:02d}" / f"{date_publication.day:02d}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def publish(
        self,
        *,
        langue: str,
        theme: str,
        date_publication: dt.date,
        article: dict[str, Any],
    ) -> PublishResult:
        try:
            target_dir = self._target_dir(date_publication)
            html_path = target_dir / f"{theme}-{langue}.html"
            meta_path = target_dir / f"{theme}-{langue}.meta.json"

            keywords = ", ".join(article.get("mots_cles_secondaires", []) or [])
            html = HTML_WRAPPER.format(
                lang=langue,
                titre=article.get("titre_editorial", ""),
                meta_desc=article.get("meta_description", ""),
                keywords=keywords,
                date_iso=date_publication.isoformat(),
                contenu=article.get("contenu_html", ""),
            )
            html_path.write_text(html, encoding="utf-8")

            sidecar = {
                "theme": theme,
                "langue": langue,
                "date_publication": date_publication.isoformat(),
                "titre_editorial": article.get("titre_editorial"),
                "titre_seo": article.get("titre_seo"),
                "slug": article.get("slug"),
                "meta_description": article.get("meta_description"),
                "focus_keyword": article.get("focus_keyword"),
                "mots_cles_secondaires": article.get("mots_cles_secondaires", []),
                "categorie_suggeree": article.get("categorie_suggeree"),
                # Champs Yoast prêts pour WordPress
                "yoast_wpseo_title": article.get("titre_seo"),
                "yoast_wpseo_metadesc": article.get("meta_description"),
                "yoast_wpseo_focuskw": article.get("focus_keyword"),
            }
            meta_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")

            # URL publique exposée par nginx (/articles/...)
            relative = html_path.relative_to(self.base_dir)
            public_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/articles/{relative.as_posix()}"

            logger.info("FilePublisher → %s", html_path)
            return PublishResult(
                success=True,
                backend=self.backend_name,
                public_url=public_url,
                file_path=str(html_path),
                metadata={"meta_path": str(meta_path)},
            )

        except Exception as exc:  # noqa: BLE001
            logger.exception("FilePublisher erreur")
            return PublishResult(
                success=False,
                backend=self.backend_name,
                error=str(exc),
            )
