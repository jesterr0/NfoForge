"""The headless core: what every NfoForge interface drives.

Nothing under this package may import PySide6. The desktop application, the
command line and any future server are callers of it, never dependencies.
"""
