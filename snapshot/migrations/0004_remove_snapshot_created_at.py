from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("snapshot", "0003_alter_accountsnapshot_options_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="accountsnapshot",
            name="created_at",
        ),
        migrations.RemoveField(
            model_name="positionsnapshot",
            name="created_at",
        ),
    ]
