from abc import ABC, abstractmethod

class MangaSitePlugin(ABC):
    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Return True if this plugin can handle the given URL."""
        pass

    @abstractmethod
    def get_image_urls(self, url: str) -> list:
        """Return a list of image URLs for the given manga page URL."""
        pass
