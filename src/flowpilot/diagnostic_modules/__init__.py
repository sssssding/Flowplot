"""Small in-process capability registry; adding a module adds one registration."""
from . import flow

MODULES = {"LaminarFlow": flow}
