from django.db import models
from pgvector.django import VectorField


class NewsArticle(models.Model):
    provider = models.CharField(max_length=50, default="yahoo")
    source = models.CharField(max_length=100)
    article_url = models.URLField(unique=True)
    title = models.CharField(max_length=500)
    content = models.TextField()
    content_hash = models.CharField(max_length=32, db_index=True)
    language = models.CharField(max_length=10, db_index=True)
    published = models.DateTimeField(db_index=True)
    fetched_at = models.DateTimeField(db_index=True, null=True, blank=True)

    class Meta:
        ordering = ["-published"]
        indexes = [
            models.Index(fields=["provider", "published"]),
            models.Index(fields=["provider", "source"]),
        ]

    def __str__(self) -> str:
        return self.title


class NewsArticleEmbedding(models.Model):
    article = models.ForeignKey(
        "news.NewsArticle",
        on_delete=models.CASCADE,
        related_name="embeddings",
    )
    chunk_index = models.PositiveIntegerField()
    chunk_text = models.TextField()
    chunk_hash = models.CharField(max_length=32)
    title = models.CharField(max_length=500)
    source = models.CharField(max_length=100)
    published = models.DateTimeField(db_index=True)
    embedding_model = models.CharField(max_length=100)
    embedding = VectorField(dimensions=1536)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["article_id", "chunk_index", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["article", "chunk_index"],
                name="uniq_news_article_chunk",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.article_id}:{self.chunk_index}"
