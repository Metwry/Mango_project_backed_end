from datetime import timedelta

from rest_framework import serializers

from shared.utils import normalize_datetime_to_utc
from snapshot.models import SnapshotLevel


class SnapshotQueryBaseSerializer(serializers.Serializer):
    level = serializers.ChoiceField(choices=SnapshotLevel.choices)
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
    limit = serializers.IntegerField(required=False, min_value=1, max_value=10000, default=2000)

    @staticmethod
    def _normalize_datetime(value):
        return normalize_datetime_to_utc(value)

    def validate(self, attrs):
        start_time = self._normalize_datetime(attrs["start_time"])
        end_time = self._normalize_datetime(attrs["end_time"])

        if start_time > end_time:
            raise serializers.ValidationError("start_time 不能晚于 end_time")

        level = attrs["level"]
        if level == SnapshotLevel.M15 and (end_time - start_time) > timedelta(days=1):
            raise serializers.ValidationError("M15 查询时间跨度最大为 1 天")

        attrs["start_time"] = start_time
        attrs["end_time"] = end_time
        return attrs


class AccountSnapshotQuerySerializer(SnapshotQueryBaseSerializer):
    account_id = serializers.IntegerField(required=False, min_value=1)


class PositionSnapshotQuerySerializer(SnapshotQueryBaseSerializer):
    account_id = serializers.IntegerField(required=False, min_value=1)
    instrument_id = serializers.IntegerField(required=False, min_value=1)
