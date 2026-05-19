"""Interface Publisher abstraite."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PublishResult:
    """Résultat d'une publication, normalisé entre backends."""
    success: bool
    backend: str
    public_url: str | None = None
    backend_post_id: int | None = None
    file_path: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Publisher(ABC):
    """Contrat commun aux backends de publication (file, wordpress)."""

    backend_name: str = "abstract"

    @abstractmethod
    def publish(
        self,
        *,
        langue: str,
        theme: str,
        date_publication,
        article: dict[str, Any],
    ) -> PublishResult:
        """
        Publie un article.

        :param langue: "fr" ou "en"
        :param theme: "meteo" / "taux_change" / ...
        :param date_publication: date Python
        :param article: dict contenant titre_editorial, titre_seo, slug,
                        meta_description, focus_keyword, mots_cles_secondaires,
                        contenu_html, categorie_suggeree
        """
        ...
