from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("investment", "0006_alter_investmentrecord_options_and_more"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="investmentrecord",
            name="investment__user_id_f54229_idx",
        ),
        migrations.RemoveIndex(
            model_name="investmentrecord",
            name="investment__cash_ac_1fa41f_idx",
        ),
        migrations.RemoveIndex(
            model_name="investmentrecord",
            name="investment__user_id_b9f1d6_idx",
        ),
        migrations.AddIndex(
            model_name="investmentrecord",
            index=models.Index(fields=["user", "instrument"], name="investment__user_id_dd7166_idx"),
        ),
    ]
