"""Pattern Publisher : interface unique, deux implémentations interchangeables."""
from app.publishers.base import Publisher, PublishResult
from app.publishers.file_publisher import FilePublisher
from app.publishers.wordpress_publisher import WordPressPublisher

from app.config import settings


def get_publisher() -> Publisher:
    """Factory : retourne l'implémentation selon PUBLISHER_BACKEND."""
    if settings.PUBLISHER_BACKEND == "wordpress":
        return WordPressPublisher()
    return FilePublisher()


__all__ = ["Publisher", "PublishResult", "FilePublisher", "WordPressPublisher", "get_publisher"]
