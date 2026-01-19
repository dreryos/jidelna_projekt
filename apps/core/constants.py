"""
Sdílené konstanty pro celou aplikaci
"""
from decimal import Decimal


# České DPH sazby platné v roce 2026
VAT_RATE_CHOICES = [
    (Decimal('21'), '21%'),  # Standardní sazba
    (Decimal('12'), '12%'),  # Snížená sazba (potraviny, stravování)
    (Decimal('0'), '0%'),    # Osvobozeno od DPH
]
