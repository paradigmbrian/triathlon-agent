"""Web settings: the coach's settings plus where the server binds and where the built app is."""

from functools import lru_cache

from tri_coach.config import CoachSettings


class WebSettings(CoachSettings):
    tri_web_host: str = "127.0.0.1"
    tri_web_port: int = 8321
    tri_web_dist: str = "web/dist"  # relative to the working directory; served when present


@lru_cache(maxsize=1)
def get_web_settings() -> WebSettings:
    return WebSettings()
