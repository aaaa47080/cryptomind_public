"""TEE spike 的 /assess HTTP 入口（Phala Cloud 部署用）。

包一層 FastAPI 讓 TEE 內的服務可被外部呼叫；真正的計算全在
assess_in_tee.assess_quote（純函式）。
"""

from __future__ import annotations

from assess_in_tee import assess_quote
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="cryptomind-tee-assess (spike)")


class QuoteIn(BaseModel):
    input_asset: str = "native"
    output_asset: str = ""
    input_units: str = ""
    min_output_amount: str = ""
    price_impact_percent: float = 0.0


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/assess")
def assess(quote: QuoteIn):
    return assess_quote(quote.model_dump())
