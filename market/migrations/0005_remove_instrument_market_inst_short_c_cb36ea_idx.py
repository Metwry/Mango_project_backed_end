from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("market", "0004_drop_symbol_like_index"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="instrument",
            name="market_inst_short_c_cb36ea_idx",
        ),
    ]
