"""PDF в Word: распознавание сканов (OCR) в редактируемый .docx без интернета."""

__version__ = "1.3.0"

try:
    from ._build import BUILD     # дата сборки, её записывает сборка .exe на GitHub
except ImportError:
    BUILD = ""
