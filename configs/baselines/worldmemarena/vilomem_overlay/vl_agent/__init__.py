"""Minimal namespace shim for the WorldMemArena ViLoMem adapter.

The benchmark bundle omits ViLoMem's declared top-level ``tools`` package, but
its upstream ``vl_agent.__init__`` eagerly imports nodes that require it.  The
WorldMemArena adapter only imports ``vl_agent.memory``.  Extending the package
path here bypasses that unrelated eager import while loading the frozen
``memory.py`` implementation unchanged from the bundled source tree.
"""

from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)
