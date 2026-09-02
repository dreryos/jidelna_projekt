"""
Rozpoznávání dodacích listů, prodejek a faktur z fotky pomocí Mistral OCR.

Moduly:
- schema: pydantic schéma, které dostane Mistral jako `document_annotation_format`
- client: volání OCR API, případně přehrání uložených fixtur bez sítě
- normalize: převod anotace na kanonický `receipt_data` dict
- quirks: dodavatelské zvláštnosti (nezbožní řádky, jednotky, násobky balení)
"""
