import json

from django.contrib.auth import get_user_model
from investment.services.query_service import build_position_list_queryset
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from market.services.instruments.queries import build_latest_quotes
from market.services.pricing.fx import load_cached_usd_rates
from market.services.refresh.usd_rates import refresh_usd_rates
from pandas import DataFrame, to_numeric
from pydantic import BaseModel, Field

from ai.config import get_prompt_text
from ai.llmmodels.model_factory import LLMModelFactory


class PositionSummaryQuery(BaseModel):
    query: str = Field(description="用户关于持仓的原始问题")
    base_currency: str | None = Field(default=None, description="可选的展示基准币种，例如 CNY、USD")


class GetPositionTool:

    def __init__(self) -> None:
        self.prompt_text = get_prompt_text("position_summary")
        self.prompt_template = ChatPromptTemplate.from_template(self.prompt_text)
        self.model = LLMModelFactory.create_chat_model(task_name="position_summary")
        self.chain = self.prompt_template | self.model | StrOutputParser()

    def get_position(self, request: dict) -> str:
        context = request.get("context") or {}
        user_id = context.get("user_id")
        if not user_id:
            raise ValueError("user_id is required")

        raw_base_currency = request.get("base_currency")
        if raw_base_currency is None:
            base_currency = "CNY"
        else:
            normalized_base_currency = str(raw_base_currency).strip().upper()
            base_currency = "CNY" if normalized_base_currency in {"", "NONE", "NULL"} else normalized_base_currency
        query = str(request.get("query", "")).strip()

        user = get_user_model().objects.get(id=user_id)
        queryset = build_position_list_queryset(user=user)

        positions = []
        for position in queryset:
            instrument = position.instrument
            currency = (instrument.base_currency or "").upper()
            if not currency:
                currency = {
                    "US": "USD",
                    "HK": "HKD",
                    "CN": "CNY",
                    "CRYPTO": "USD",
                }.get(instrument.market, "CNY")

            positions.append(
                {
                    "instrument_id": position.instrument_id,
                    "symbol": instrument.symbol,
                    "short_code": instrument.short_code,
                    "name": instrument.name,
                    "market": instrument.market,
                    "price_currency": currency,
                    "quantity": float(position.quantity),
                    "avg_cost_local": float(position.avg_cost),
                    "cost_total_local": float(position.cost_total),
                    "realized_pnl_total": float(position.realized_pnl_total),
                }
            )

        if not positions:
            analysis_result = {
                "user_id": user_id,
                "base_currency": base_currency,
                "summary": {
                    "position_count": 0,
                    "total_cost_base": 0.0,
                    "total_market_value_base": 0.0,
                    "total_unrealized_pnl_base": 0.0,
                },
                "market_distribution": [],
                "positions": [],
            }
            return self.chain.invoke(
                {
                    "query": query,
                    "position_data": json.dumps(analysis_result, ensure_ascii=False),
                }
            ).strip()

        quote_items = [
            {
                "market": item["market"],
                "short_code": item["short_code"],
            }
            for item in positions
        ]
        quotes = build_latest_quotes(quote_items)
        usd_rates = load_cached_usd_rates()
        if len(usd_rates) <= 1:
            refresh_usd_rates()
            usd_rates = load_cached_usd_rates()
        if base_currency not in usd_rates:
            raise ValueError(f"unsupported base currency: {base_currency}")
        base_usd_rate = float(usd_rates[base_currency])

        df = DataFrame(positions)
        quote_df = DataFrame(quotes)
        df = df.merge(
            quote_df[["market", "short_code", "latest_price"]],
            on=["market", "short_code"],
            how="left",
        )

        df["latest_price"] = to_numeric(df["latest_price"], errors="coerce").fillna(0.0)
        df["fx_rate"] = df["price_currency"].map(
            lambda currency: 1.0
            if currency == base_currency
            else (base_usd_rate / float(usd_rates.get(currency, 1.0)))
        )
        df["avg_cost_base"] = df["avg_cost_local"] * df["fx_rate"]
        df["cost_total_base"] = df["cost_total_local"] * df["fx_rate"]
        df["market_value_base"] = df["quantity"] * df["latest_price"] * df["fx_rate"]
        df["unrealized_pnl_base"] = df["market_value_base"] - df["cost_total_base"]
        df["price_ready"] = df["latest_price"] > 0

        total_market_value_base = float(df["market_value_base"].sum())
        total_cost_base = float(df["cost_total_base"].sum())
        total_unrealized_pnl_base = float(df["unrealized_pnl_base"].sum())

        if total_market_value_base > 0:
            df["position_weight"] = df["market_value_base"] / total_market_value_base
        else:
            df["position_weight"] = 0.0

        market_distribution_df = (
            df.groupby("market", dropna=False)["market_value_base"]
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

        df = df.sort_values(by="market_value_base", ascending=False)

        analysis_result = {
            "user_id": user_id,
            "base_currency": base_currency,
            "summary": {
                "position_count": int(len(df)),
                "total_cost_base": round(total_cost_base, 4),
                "total_market_value_base": round(total_market_value_base, 4),
                "total_unrealized_pnl_base": round(total_unrealized_pnl_base, 4),
            },
            "market_distribution": market_distribution_df.to_dict(orient="records"),
            "positions": df[
                [
                    "instrument_id",
                    "symbol",
                    "short_code",
                    "name",
                    "market",
                    "price_currency",
                    "quantity",
                    "latest_price",
                    "avg_cost_base",
                    "cost_total_base",
                    "market_value_base",
                    "unrealized_pnl_base",
                    "position_weight",
                    "price_ready",
                ]
            ].to_dict(orient="records"),
        }
        return self.chain.invoke(
            {
                "query": query,
                "position_data": json.dumps(analysis_result, ensure_ascii=False),
            }
        ).strip()
