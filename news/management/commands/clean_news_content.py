from __future__ import annotations

from django.core.management.base import BaseCommand

from news.service import NewsContentCleanupService


class Command(BaseCommand):
    help = "Re-clean stored news content and clear stale embeddings for updated articles."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *args, **options) -> None:
        stats = NewsContentCleanupService().clean_articles(limit=options["limit"])
        self.stdout.write(self.style.SUCCESS(str(stats)))
