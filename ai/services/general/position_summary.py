from __future__ import annotations

from django.contrib.auth import get_user_model
from investment.services.query_service import get_position_data as query_position_data
from market.services.instruments.queries import build_latest_quotes
from market.services.pricing import convert_currency
from pandas import DataFrame, to_numeric

SUMMARY_BASE_CURRENCY = "CNY"


class PositionSummaryService:
    def summarize(self, *, user_id: int, query: str, symbols: list[str] | None = None) -> dict:
        user = get_user_model().objects.get(id=user_id)
        position_payload = query_position_data(user=user, symbols=symbols)
        positions = position_payload["positions"]

        if not positions:
            return {
                "query": query,
                "base_currency": SUMMARY_BASE_CURRENCY,
                "summary": {
                    "position_count": "0",
                    "total_cost_base": "0.00",
                    "total_market_value_base": "0.00",
                    "total_unrealized_pnl_base": "0.00",
                },
                "market_distribution": [],
                "positions": [],
            }

        quote_items = [
            {"market": item["market"], "short_code": item["symbol"]}
            for item in positions
        ]
        quotes = build_latest_quotes(quote_items)
        quote_df = DataFrame(quotes)
        position_df = DataFrame(positions)
        if quote_df.empty:
            quote_df = DataFrame(columns=["market", "short_code", "latest_price"])
        position_df = position_df.merge(
            quote_df[["market", "short_code", "latest_price"]],
            left_on=["market", "symbol"],
            right_on=["market", "short_code"],
            how="left",
        )

        position_df["quantity_value"] = to_numeric(position_df["quantity"], errors="coerce").fillna(0.0)
        position_df["avg_cost_value"] = to_numeric(position_df["avg_cost"], errors="coerce").fillna(0.0)
        position_df["cost_total_value"] = to_numeric(position_df["cost_total"], errors="coerce").fillna(0.0)
        position_df["latest_price"] = to_numeric(position_df["latest_price"], errors="coerce").fillna(0.0)
        position_df["market_value_local"] = position_df["quantity_value"] * position_df["latest_price"]

        cost_converted = convert_currency(
            amounts=[
                {
                    "key": f"cost_total::{row['symbol']}",
                    "amount": row["cost_total"],
                    "currency": row["currency"],
                }
                for _, row in position_df.iterrows()
            ],
            base_currency=SUMMARY_BASE_CURRENCY,
        )
        market_value_converted = convert_currency(
            amounts=[
                {
                    "key": f"market_value::{row['symbol']}",
                    "amount": str(row["market_value_local"]),
                    "currency": row["currency"],
                }
                for _, row in position_df.iterrows()
            ],
            base_currency=SUMMARY_BASE_CURRENCY,
        )
        avg_cost_converted = convert_currency(
            amounts=[
                {
                    "key": f"avg_cost::{row['symbol']}",
                    "amount": row["avg_cost"],
                    "currency": row["currency"],
                }
                for _, row in position_df.iterrows()
            ],
            base_currency=SUMMARY_BASE_CURRENCY,
        )

        cost_map = {item["key"]: item["converted_amount"] for item in cost_converted["items"]}
        market_value_map = {item["key"]: item["converted_amount"] for item in market_value_converted["items"]}
        avg_cost_map = {item["key"]: item["converted_amount"] for item in avg_cost_converted["items"]}

        position_df["avg_cost_base"] = position_df["symbol"].map(
            lambda symbol: float(avg_cost_map.get(f"avg_cost::{symbol}", "0"))
        )
        position_df["cost_total_base"] = position_df["symbol"].map(
            lambda symbol: float(cost_map.get(f"cost_total::{symbol}", "0"))
        )
        position_df["market_value_base"] = position_df["symbol"].map(
            lambda symbol: float(market_value_map.get(f"market_value::{symbol}", "0"))
        )
        position_df["unrealized_pnl_base"] = (
            position_df["market_value_base"] - position_df["cost_total_base"]
        )
        position_df["price_ready"] = position_df["latest_price"] > 0

        total_market_value_base = float(position_df["market_value_base"].sum())
        total_cost_base = float(position_df["cost_total_base"].sum())
        total_unrealized_pnl_base = float(position_df["unrealized_pnl_base"].sum())

        if total_market_value_base > 0:
            position_df["position_weight"] = (
                position_df["market_value_base"] / total_market_value_base
            )
        else:
            position_df["position_weight"] = 0.0

        market_distribution_df = (
            position_df.groupby("market", dropna=False)["market_value_base"]
            .sum()
            .reset_index()
            .sort_values(by="market_value_base", ascending=False)
        )
        if total_market_value_base > 0:
            market_distribution_df["weight"] = (
                market_distribution_df["market_value_base"] / total_market_value_base
            )
        else:
            market_distribution_df["weight"] = 0.0

        position_df = position_df.sort_values(by="market_value_base", ascending=False)
        return {
            "query": query,
            "base_currency": SUMMARY_BASE_CURRENCY,
            "summary": {
                "position_count": str(len(position_df)),
                "total_cost_base": f"{total_cost_base:.2f}",
                "total_market_value_base": f"{total_market_value_base:.2f}",
                "total_unrealized_pnl_base": f"{total_unrealized_pnl_base:.2f}",
            },
            "market_distribution": [
                {
                    "market": str(row["market"]),
                    "market_value_base": f"{float(row['market_value_base']):.2f}",
                    "weight": f"{float(row['weight']):.6f}",
                }
                for row in market_distribution_df.to_dict(orient="records")
            ],
            "positions": [
                {
                    "symbol": str(row["symbol"]),
                    "name": str(row["name"]),
                    "market": str(row["market"]),
                    "price_currency": str(row["currency"]),
                    "quantity": str(row["quantity"]),
                    "latest_price": f"{float(row['latest_price']):.4f}",
                    "avg_cost_base": f"{float(row['avg_cost_base']):.2f}",
                    "cost_total_base": f"{float(row['cost_total_base']):.2f}",
                    "market_value_base": f"{float(row['market_value_base']):.2f}",
                    "unrealized_pnl_base": f"{float(row['unrealized_pnl_base']):.2f}",
                    "position_weight": f"{float(row['position_weight']):.6f}",
                    "price_ready": bool(row["price_ready"]),
                }
                for row in position_df.to_dict(orient="records")
            ],
        }
