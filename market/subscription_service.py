from django.db import transaction

from .models import UserInstrumentSubscription

SOURCE_POSITION = "position"
SOURCE_WATCHLIST = "watchlist"
SOURCE_TO_FIELD = {
    SOURCE_POSITION: "from_position",
    SOURCE_WATCHLIST: "from_watchlist",
}


def set_user_instrument_source(*, user, instrument, source: str, enabled: bool) -> UserInstrumentSubscription | None:
    field_name = SOURCE_TO_FIELD.get(source)
    if field_name is None:
        raise ValueError(f"unknown source: {source}")

    with transaction.atomic():
        subscription = (
            UserInstrumentSubscription.objects
            .select_for_update()
            .filter(user=user, instrument=instrument)
            .first()
        )

        if subscription is None:
            if not enabled:
                return None

            payload = {
                "from_position": source == SOURCE_POSITION,
                "from_watchlist": source == SOURCE_WATCHLIST,
            }
            return UserInstrumentSubscription.objects.create(
                user=user,
                instrument=instrument,
                **payload,
            )

        setattr(subscription, field_name, bool(enabled))
        if not subscription.from_position and not subscription.from_watchlist:
            subscription.delete()
            return None

        subscription.save(update_fields=[field_name, "updated_at"])
        return subscription


def has_any_subscription_for_instrument(*, instrument_id: int) -> bool:
    return UserInstrumentSubscription.objects.filter(instrument_id=instrument_id).exists()
