from django.conf import settings
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
        constraints = [
            models.UniqueConstraint(
                fields=["source_type", "source_id"],
                name="uniq_ai_analysis_source",
            ),
        ]
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


class ChatSession(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_sessions",
        db_index=True,
    )
    title = models.CharField(max_length=200)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_chat_session"
        verbose_name = "AI 会话"
        verbose_name_plural = "AI 会话"
        ordering = ["-updated_at", "-id"]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.title}"


class ChatMessage(models.Model):
    class Role(models.TextChoices):
        USER = "USER", "USER"
        ASSISTANT = "ASSISTANT", "ASSISTANT"

    session = models.ForeignKey(
        "ai.ChatSession",
        on_delete=models.CASCADE,
        related_name="messages",
        db_index=True,
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    content = models.TextField()
    sequence = models.PositiveIntegerField()

    class Meta:
        db_table = "ai_chat_message"
        verbose_name = "AI 消息"
        verbose_name_plural = "AI 消息"
        ordering = ["session_id", "sequence", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "sequence"],
                name="uniq_ai_chat_message_session_sequence",
            ),
        ]
        indexes = [
            models.Index(fields=["session", "sequence"], name="ai_chat_msg_session_seq_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.session_id}:{self.role}:{self.sequence}"
