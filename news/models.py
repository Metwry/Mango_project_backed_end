from django.db import models


class NewsArticle(models.Model):
    provider = models.CharField(max_length=50, default="yahoo")
    source = models.CharField(max_length=100)
    article_url = models.URLField(unique=True)
    content = models.TextField()
    content_hash = models.CharField(max_length=64, db_index=True)
    published = models.DateTimeField(db_index=True)
    title = models.CharField(max_length=500)

    class Meta:
        ordering = ["-published"]
        indexes = [
            models.Index(fields=["provider", "published"]),
            models.Index(fields=["provider", "source"]),
        ]

    def __str__(self) -> str:
        return self.title
