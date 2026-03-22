from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("snapshot", "0005_remove_positionsnapshot_price_time"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="positionsnapshot",
            name="snap_pos_quantity_gte_0",
        ),
    ]
