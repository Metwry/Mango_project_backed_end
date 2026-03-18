from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("market", "0003_alter_instrument_is_active_alter_instrument_symbol"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP INDEX IF EXISTS market_instrument_symbol_0d709786_like;",
            reverse_sql=(
                "CREATE INDEX market_instrument_symbol_0d709786_like "
                "ON market_instrument (symbol varchar_pattern_ops);"
            ),
        ),
    ]
