"""Same-domain local source processors (TXT/CSV/TSV/DOCX/PDF/XLSX/image/audio/video).

Each module owns one format family and shares :mod:`contracts` for bounds, schema-2
locators and the processor identity it must report. Nothing here performs network,
model, database or storage work.
"""
