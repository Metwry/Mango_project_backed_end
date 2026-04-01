from django.db import models


class AIAnalysis(models.Model):
    class SourceType(models.TextChoices):
        NEWS_ARTICLE = "news_article", "News Article"

    source_type = models.CharField(
        max_length=50,
        choices=SourceType.choices,
        db_index=True,
    )
    source_id = models.BigIntegerField(db_index=True)
    topic = models.CharField(max_length=100, db_index=True)
    summary_short = models.TextField()
    summary_long = models.TextField()
    sentiment = models.CharField(max_length=20, db_index=True)
    impact_level = models.CharField(max_length=20, db_index=True)
    model_name = models.CharField(max_length=100)
    prompt_name = models.CharField(max_length=100)
    analyzed_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-analyzed_at", "-id"]
        indexes = [
            models.Index(fields=["source_type", "source_id"]),
            models.Index(fields=["topic", "analyzed_at"]),
            models.Index(fields=["sentiment", "impact_level"]),
        ]

    def __str__(self) -> str:
        return f"{self.source_type}:{self.source_id} - {self.topic}"


class AIAnalysisInstrument(models.Model):
    ai_analysis = models.ForeignKey(
        "ai.AIAnalysis",
        on_delete=models.CASCADE,
        related_name="instrument_links",
    )
    instrument = models.ForeignKey(
        "market.Instrument",
        on_delete=models.CASCADE,
        related_name="ai_analysis_links",
    )

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["ai_analysis", "instrument"],
                name="uniq_ai_analysis_instrument",
            ),
        ]
        indexes = [
            models.Index(fields=["instrument"]),
        ]

    def __str__(self) -> str:
        return f"{self.ai_analysis_id}-{self.instrument_id}"


class AIAnalysisCountry(models.Model):
    ai_analysis = models.ForeignKey(
        "ai.AIAnalysis",
        on_delete=models.CASCADE,
        related_name="country_links",
    )
    country_name = models.CharField(max_length=100, db_index=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["ai_analysis", "country_name"],
                name="uniq_ai_analysis_country",
            ),
        ]
        indexes = [
            models.Index(fields=["country_name"]),
        ]

    def __str__(self) -> str:
        return f"{self.ai_analysis_id}-{self.country_name}"


class AIAnalysisTag(models.Model):
    ai_analysis = models.ForeignKey(
        "ai.AIAnalysis",
        on_delete=models.CASCADE,
        related_name="tag_links",
    )
    tag_name = models.CharField(max_length=100, db_index=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["ai_analysis", "tag_name"],
                name="uniq_ai_analysis_tag",
            ),
        ]
        indexes = [
            models.Index(fields=["tag_name"]),
        ]

    def __str__(self) -> str:
        return f"{self.ai_analysis_id}-{self.tag_name}"
