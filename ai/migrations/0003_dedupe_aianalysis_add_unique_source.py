from django.db import migrations, models


def dedupe_ai_analysis(apps, schema_editor):
    AIAnalysis = apps.get_model("ai", "AIAnalysis")

    duplicate_keys = (
        AIAnalysis.objects.values("source_type", "source_id")
        .order_by()
        .annotate(row_count=models.Count("id"))
        .filter(row_count__gt=1)
    )

    for duplicate in duplicate_keys.iterator():
        analyses = list(
            AIAnalysis.objects.filter(
                source_type=duplicate["source_type"],
                source_id=duplicate["source_id"],
            ).order_by("-analyzed_at", "-id")
        )
        for stale in analyses[1:]:
            stale.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0002_rename_ai_aianalys_source__1f6a80_idx_ai_aianalys_source__676100_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(dedupe_ai_analysis, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="aianalysis",
            constraint=models.UniqueConstraint(
                fields=("source_type", "source_id"),
                name="uniq_ai_analysis_source",
            ),
        ),
    ]
