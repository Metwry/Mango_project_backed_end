from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("snapshot", "0006_remove_positionsnapshot_quantity_constraint"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="accountsnapshot",
            name="snap_acc_fx_rate_null_or_gt_0",
        ),
        migrations.RemoveConstraint(
            model_name="positionsnapshot",
            name="snap_pos_avg_cost_gte_0",
        ),
        migrations.RemoveConstraint(
            model_name="positionsnapshot",
            name="snap_pos_market_price_null_or_gt_0",
        ),
        migrations.RemoveConstraint(
            model_name="positionsnapshot",
            name="snap_pos_market_value_null_or_gte_0",
        ),
        migrations.RemoveConstraint(
            model_name="positionsnapshot",
            name="snap_pos_market_usd_null_or_gte_0",
        ),
        migrations.RemoveConstraint(
            model_name="positionsnapshot",
            name="snap_pos_fx_rate_null_or_gt_0",
        ),
        migrations.RemoveConstraint(
            model_name="positionsnapshot",
            name="snap_pos_status_price_consistent",
        ),
    ]
