"""Minimal namespace shim for the ViLoMem ``common`` package.

The adapter's memory module only needs ``common.retry``.  The bundled upstream
``common.__init__`` eagerly imports evaluation utilities whose declared
``tools`` package is absent from the WorldMemArena snapshot.  This shim extends
the package path and leaves ``common.retry`` itself untouched.
"""

from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)
