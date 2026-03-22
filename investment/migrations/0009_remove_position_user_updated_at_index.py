from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("investment", "0008_remove_investmentrecord_invrec_buy_realized_pnl_null_and_more"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="position",
            name="investment__user_id_26ec0b_idx",
        ),
    ]
