from django.db import migrations


# Kolace `czech` se v kódu používá přes Collate('name', 'czech') na čtyřech
# místech - v Ingredient.Meta.ordering (a tedy i v migraci 0010),
# v apps/inventory/views.py a v apps/production/views.py. Na SQLite ji
# registruje apps/core/collation.py při každém spojení; PostgreSQL nic
# takového nemá a dotaz by skončil chybou
# `collation "czech" for encoding "UTF8" does not exist`.
#
# ICU s locale cs-CZ řadí stejně jako naše Python implementace - „ch" mezi
# H a I. obraz postgres:17-alpine je s ICU sestavený.
#
# `run_before` je podstatné: kolace musí existovat dřív, než jakákoli jiná
# migrace (i z jiné aplikace) položí dotaz nad Ingredient s výchozím řazením.
# Stačí, že takový dotaz vznikne - prázdná tabulka chybu nezachrání, protože
# PostgreSQL kolaci řeší při plánování, ne až nad daty.
CREATE_COLLATION = """
    CREATE COLLATION IF NOT EXISTS czech (provider = icu, locale = 'cs-CZ');
"""

DROP_COLLATION = """
    DROP COLLATION IF EXISTS czech;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    run_before = [
        ('core', '0002_category_remove_recipeingredient_quantity_adult_and_more'),
    ]

    operations = [
        migrations.RunSQL(
            sql=CREATE_COLLATION,
            reverse_sql=DROP_COLLATION,
        ),
    ]
