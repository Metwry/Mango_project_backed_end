from __future__ import annotations

from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

try:
    import pandas_market_calendars as mcal
except Exception:  # pragma: no cover - runtime dependency
    mcal = None


MARKET_CONFIG = {
    "US": {
        "timezone": "America/New_York",
        "calendar_names": ("NYSE", "NASDAQ"),
    },
    "CN": {
        "timezone": "Asia/Shanghai",
        "calendar_names": ("SSE",),
    },
    "HK": {
        "timezone": "Asia/Hong_Kong",
        "calendar_names": ("HKEX", "XHKG"),
    },
}


def _parse_date(raw: str) -> date:
    try:
        return date.fromisoformat(str(raw).strip())
    except ValueError as exc:
        raise CommandError(f"invalid date: {raw}") from exc


def _calendar_output_dir(raw: str | None) -> Path:
    if raw:
        return Path(raw).resolve()
    return (Path(getattr(settings, "BASE_DIR", Path.cwd())) / "resource" / "data" / "market_calendars").resolve()


def _load_calendar(calendar_names: tuple[str, ...]):
    if mcal is None:
        raise CommandError(
            "pandas_market_calendars is required. Install it first: pip install pandas_market_calendars"
        )
    last_exc = None
    for name in calendar_names:
        try:
            return mcal.get_calendar(name), name
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
    raise CommandError(f"unable to load calendar from candidates={calendar_names}: {last_exc}")


class Command(BaseCommand):
    help = "Generate trading calendar CSV files (US/CN/HK) from pandas_market_calendars."

    def add_arguments(self, parser):
        parser.add_argument("--start", required=True, help="Start date in YYYY-MM-DD")
        parser.add_argument("--end", required=True, help="End date in YYYY-MM-DD")
        parser.add_argument(
            "--markets",
            nargs="*",
            default=["US", "CN", "HK"],
            help="Markets to generate. Default: US CN HK",
        )
        parser.add_argument(
            "--out-dir",
            default="",
            help="Output directory. Default: <BASE_DIR>/resource/data/market_calendars",
        )

    def handle(self, *args, **options):
        start = _parse_date(options["start"])
        end = _parse_date(options["end"])
        if start > end:
            raise CommandError("start date must be <= end date")

        markets = {str(x).strip().upper() for x in (options.get("markets") or []) if str(x).strip()}
        unknown = sorted(markets - set(MARKET_CONFIG.keys()))
        if unknown:
            raise CommandError(f"unsupported markets: {', '.join(unknown)}")
        if not markets:
            raise CommandError("no markets selected")

        out_dir = _calendar_output_dir(options.get("out_dir"))
        out_dir.mkdir(parents=True, exist_ok=True)

        generated_files = 0
        for market in sorted(markets):
            cfg = MARKET_CONFIG[market]
            cal, cal_name = _load_calendar(cfg["calendar_names"])
            tz = ZoneInfo(cfg["timezone"])
            schedule = cal.schedule(start_date=start.isoformat(), end_date=end.isoformat())
            if schedule is None or schedule.empty:
                self.stdout.write(self.style.WARNING(f"[{market}] empty schedule, skip"))
                continue

            df = schedule.reset_index().rename(columns={"index": "trade_day"})
            df["trade_day"] = df["trade_day"].dt.tz_localize(None).dt.date
            df["market_open_local"] = df["market_open"].dt.tz_convert(tz)
            df["market_close_local"] = df["market_close"].dt.tz_convert(tz)
            df["is_half_day"] = (
                (df["market_close_local"].dt.hour * 60 + df["market_close_local"].dt.minute)
                < (16 * 60)
            )

            generated_at = timezone.now().astimezone(ZoneInfo("UTC")).replace(microsecond=0).isoformat()
            rows_by_year: dict[int, list[dict]] = {}
            for _, row in df.iterrows():
                trade_day = row["trade_day"]
                record = {
                    "market": market,
                    "trade_date": trade_day.isoformat(),
                    "timezone": cfg["timezone"],
                    "is_open": "1",
                    "market_open_local": row["market_open_local"].replace(microsecond=0).isoformat(),
                    "market_close_local": row["market_close_local"].replace(microsecond=0).isoformat(),
                    "market_open_utc": row["market_open"].tz_convert(ZoneInfo("UTC")).replace(microsecond=0).isoformat(),
                    "market_close_utc": row["market_close"].tz_convert(ZoneInfo("UTC")).replace(microsecond=0).isoformat(),
                    "is_half_day": "1" if bool(row["is_half_day"]) else "0",
                    "session_tag": "",
                    "source": f"pandas_market_calendars:{cal_name}",
                    "generated_at_utc": generated_at,
                }
                rows_by_year.setdefault(trade_day.year, []).append(record)

            headers = [
                "market",
                "trade_date",
                "timezone",
                "is_open",
                "market_open_local",
                "market_close_local",
                "market_open_utc",
                "market_close_utc",
                "is_half_day",
                "session_tag",
                "source",
                "generated_at_utc",
            ]
            for year, year_rows in sorted(rows_by_year.items()):
                out_file = out_dir / f"{market}_{year}.csv"
                with open(out_file, "w", encoding="utf-8", newline="") as fp:
                    fp.write(",".join(headers) + "\n")
                    for record in year_rows:
                        line = ",".join(str(record.get(h, "")) for h in headers)
                        fp.write(f"{line}\n")
                generated_files += 1
                self.stdout.write(self.style.SUCCESS(f"[{market}] wrote {out_file} rows={len(year_rows)}"))

        self.stdout.write(self.style.SUCCESS(f"done. generated_files={generated_files} out_dir={out_dir}"))
