import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_transaction_source"),
        ("investment", "0004_move_snapshot_models_to_snapshot_app"),
    ]

    operations = [
        migrations.AddField(
            model_name="investmentrecord",
            name="cash_transaction",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="investment_record",
                to="accounts.transaction",
            ),
        ),
    ]
