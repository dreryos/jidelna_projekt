# -*- coding: utf-8 -*-
# This file is distributed under the same license as the Django package.
#
# Formáty pro českou lokalizaci
from django.conf.locale.cs import formats as cs_formats

# Přepsání výchozích formátů
DECIMAL_SEPARATOR = ','
THOUSAND_SEPARATOR = '\xa0'  # non-breaking space
NUMBER_GROUPING = 3

# Formáty data a času
DATE_FORMAT = 'j. E Y'
TIME_FORMAT = 'H:i'
DATETIME_FORMAT = 'j. E Y H:i'
YEAR_MONTH_FORMAT = 'F Y'
MONTH_DAY_FORMAT = 'j. F'
SHORT_DATE_FORMAT = 'd.m.Y'
SHORT_DATETIME_FORMAT = 'd.m.Y H:i'
