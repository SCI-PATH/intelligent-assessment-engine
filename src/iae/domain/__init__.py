"""Clean Architecture domain layer.

Currently re-exports core modules so callers can migrate toward ``iae.domain``.
"""

from iae.core import models as models
from iae.core import protocols as protocols
from iae.core import settings as settings

__all__ = ["models", "protocols", "settings"]
