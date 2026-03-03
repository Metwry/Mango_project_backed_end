from __future__ import annotations

import concurrent.futures as cf
from dataclasses import dataclass
import sys

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from market.models import Instrument
from market.services.logo_service import build_logo_metadata, extract_logo_theme_color


@dataclass
class SyncStats:
    scanned: int = 0
    updated: int = 0
    skipped_unchanged: int = 0
    skipped_unsupported: int = 0


class Command(BaseCommand):
    help = "Sync logo_url/logo_color/logo_source/logo_updated_at for instruments (default: US + CRYPTO)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--markets",
            nargs="*",
            choices=["us", "crypto"],
            default=["us", "crypto"],
            help="Markets to sync. Default: us crypto",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force overwrite existing logo fields.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Bulk update batch size. Default: 1000",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without writing to database.",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=12,
            help="Thread workers for logo color extraction. Default: 12",
        )

    def handle(self, *args, **options):
        selected = set(options.get("markets") or ["us", "crypto"])
        force = bool(options.get("force"))
        dry_run = bool(options.get("dry_run"))
        batch_size = max(1, int(options.get("batch_size") or 1000))
        workers = max(1, int(options.get("workers") or 12))

        target_markets = []
        if "us" in selected:
            target_markets.append(Instrument.Market.US)
        if "crypto" in selected:
            target_markets.append(Instrument.Market.CRYPTO)

        qs = Instrument.objects.filter(market__in=target_markets).only(
            "id",
            "short_code",
            "market",
            "logo_url",
            "logo_color",
            "logo_source",
            "logo_updated_at",
        )
        if not force:
            qs = qs.filter(
                Q(logo_url__isnull=True)
                | Q(logo_url="")
                | Q(logo_color__isnull=True)
                | Q(logo_color="")
                | Q(logo_source__isnull=True)
                | Q(logo_source="")
            )

        stats = SyncStats()
        total = qs.count()
        now = timezone.now()
        to_update: list[Instrument] = []
        candidates: list[tuple[Instrument, str, str]] = []
        progress_step = 50
        processed = 0

        self._render_progress(
            current=0,
            total=total,
            updated=0,
            skipped=0,
            done=False,
        )

        for idx, inst in enumerate(qs.iterator(chunk_size=batch_size), start=1):
            stats.scanned += 1
            logo_url, logo_source = build_logo_metadata(short_code=inst.short_code, market=inst.market)
            if not logo_url or not logo_source:
                stats.skipped_unsupported += 1
                processed += 1
                if idx % progress_step == 0 or idx == total:
                    self._render_progress(
                        current=processed,
                        total=total,
                        updated=len(to_update),
                        skipped=stats.skipped_unsupported + stats.skipped_unchanged,
                        done=False,
                    )
                continue

            candidates.append((inst, logo_url, logo_source))

        def _handle_candidate(inst: Instrument, logo_url: str, logo_source: str, logo_color: str | None) -> None:
            nonlocal processed
            changed = force or (
                inst.logo_url != logo_url
                or inst.logo_color != logo_color
                or inst.logo_source != logo_source
                or inst.logo_updated_at is None
            )
            if changed:
                inst.logo_url = logo_url
                inst.logo_color = logo_color
                inst.logo_source = logo_source
                inst.logo_updated_at = now
                to_update.append(inst)
            else:
                stats.skipped_unchanged += 1

            processed += 1
            if processed % progress_step == 0 or processed == total:
                self._render_progress(
                    current=processed,
                    total=total,
                    updated=len(to_update),
                    skipped=stats.skipped_unsupported + stats.skipped_unchanged,
                    done=False,
                )

        if workers == 1:
            for inst, logo_url, logo_source in candidates:
                _handle_candidate(inst, logo_url, logo_source, extract_logo_theme_color(logo_url))
        else:
            # Bounded in-flight tasks to avoid spawning too many futures for large datasets.
            max_in_flight = max(workers, workers * 4)
            with cf.ThreadPoolExecutor(max_workers=workers) as executor:
                it = iter(candidates)
                future_to_row: dict[cf.Future, tuple[Instrument, str, str]] = {}

                def _submit_next() -> bool:
                    try:
                        row = next(it)
                    except StopIteration:
                        return False
                    inst, logo_url, logo_source = row
                    future = executor.submit(extract_logo_theme_color, logo_url)
                    future_to_row[future] = (inst, logo_url, logo_source)
                    return True

                for _ in range(min(max_in_flight, len(candidates))):
                    _submit_next()

                while future_to_row:
                    done, _ = cf.wait(future_to_row.keys(), return_when=cf.FIRST_COMPLETED)
                    for future in done:
                        inst, logo_url, logo_source = future_to_row.pop(future)
                        try:
                            logo_color = future.result()
                        except Exception:
                            logo_color = None
                        _handle_candidate(inst, logo_url, logo_source, logo_color)
                        _submit_next()

        stats.updated = len(to_update)
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run enabled: no database changes were written."))
        elif to_update:
            Instrument.objects.bulk_update(
                to_update,
                fields=["logo_url", "logo_color", "logo_source", "logo_updated_at"],
                batch_size=batch_size,
            )
        self._render_progress(
            current=total,
            total=total,
            updated=stats.updated,
            skipped=stats.skipped_unsupported + stats.skipped_unchanged,
            done=True,
        )

        self.stdout.write(
            self.style.SUCCESS(
                "sync_logo_data done "
                f"scanned={stats.scanned} updated={stats.updated} "
                f"skipped_unchanged={stats.skipped_unchanged} "
                f"skipped_unsupported={stats.skipped_unsupported} "
                f"force={force} dry_run={dry_run} workers={workers}"
            )
        )

    def _render_progress(self, *, current: int, total: int, updated: int, skipped: int, done: bool) -> None:
        total_safe = max(total, 1)
        if total == 0:
            ratio = 1.0 if done else 0.0
        else:
            ratio = min(max(current / total_safe, 0.0), 1.0)
        bar_len = 30
        filled = int(bar_len * ratio)
        bar = "#" * filled + "-" * (bar_len - filled)
        msg = (
            f"[{bar}] {ratio * 100:6.2f}% "
            f"{current}/{total} updated={updated} skipped={skipped}"
        )
        ending = "\n" if done else "\r"
        sys.stdout.write(msg + ending)
        sys.stdout.flush()
