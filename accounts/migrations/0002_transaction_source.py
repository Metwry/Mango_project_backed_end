from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="transaction",
            name="source",
            field=models.CharField(
                choices=[("manual", "手工记账"), ("investment", "投资交易"), ("reversal", "冲正流水")],
                db_index=True,
                default="manual",
                max_length=16,
            ),
        ),
    ]
