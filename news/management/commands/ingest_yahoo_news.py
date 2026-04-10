from __future__ import annotations

from django.core.management.base import BaseCommand

from news.tasks import ingest_yahoo_news


class Command(BaseCommand):
    help = "Fetch Yahoo Finance news.txt and persist deduplicated articles."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--concurrency", type=int, default=10)

    def handle(self, *args, **options) -> None:
        stats = ingest_yahoo_news(
            limit=options["limit"],
            concurrency=options["concurrency"],
        )
        self.stdout.write(self.style.SUCCESS(str(stats)))
