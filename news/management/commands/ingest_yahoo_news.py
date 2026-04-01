from __future__ import annotations

from django.core.management.base import BaseCommand

from news.tasks import ingest_yahoo_news


class Command(BaseCommand):
    help = "Fetch Yahoo Finance news, deduplicate, persist, and optionally run AI analysis."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--concurrency", type=int, default=10)
        parser.add_argument(
            "--no-analyze",
            action="store_true",
            help="Skip AI analysis and only persist news articles.",
        )

    def handle(self, *args, **options) -> None:
        stats = ingest_yahoo_news(
            limit=options["limit"],
            concurrency=options["concurrency"],
            analyze=not options["no_analyze"],
        )
        self.stdout.write(self.style.SUCCESS(str(stats)))
