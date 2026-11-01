"""
core/lazy_import.py - Moduli importati al primo utilizzo.

``ssl``, ``urllib.request`` e ``http.client`` pesano decine di MB e centinaia di
ms, ma servono ai plugin solo quando l'utente fa davvero una richiesta di rete.
"""

from __future__ import annotations

import importlib
from types import ModuleType


class LazyModule(ModuleType):
    """Proxy di un modulo: lo importa al primo attributo letto.

    Risolve anche i sottomoduli, così ``urllib = LazyModule("urllib")`` rende
    ``urllib.request.urlopen`` senza importare ``urllib.request`` in anticipo.
    """

    def __getattr__(self, name: str):
        real = importlib.import_module(self.__name__)
        try:
            value = getattr(real, name)
        except AttributeError:
            try:
                value = importlib.import_module(f"{self.__name__}.{name}")
            except ImportError:
                raise AttributeError(name) from None
        return value
