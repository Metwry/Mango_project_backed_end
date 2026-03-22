from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("snapshot", "0004_remove_snapshot_created_at"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="positionsnapshot",
            name="price_time",
        ),
    ]
