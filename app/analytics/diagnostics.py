import pandas as pd
from typing import Dict, Any

from app.analytics.comparisons import build_period_comparison


def build_drop_reason(current_df: pd.DataFrame, compare_df: pd.DataFrame) -> Dict[str, Any]:
    comp = build_period_comparison(current_df, compare_df)
    d = comp["delta_pct"]
    reasons = []

    if d.get("results") is not None and d["results"] < 0:
        if d.get("p75_rate_pct") is not None and d["p75_rate_pct"] < -20:
            reasons.append("انخفاض قوي في جودة المشاهدة العميقة للفيديو")
        if d.get("ctr_pct") is not None and d["ctr_pct"] < -15:
            reasons.append("هبوط واضح في CTR، وده يرجح ضعف الهوك أو الإبداع أو الاستهداف")
        if d.get("click_to_result_rate_pct") is not None and d["click_to_result_rate_pct"] < -15:
            reasons.append("ما بعد النقر ضعيف: المشكلة أقرب إلى الفورم أو نية الجمهور أو العرض")
        if d.get("cpl") is not None and d["cpl"] > 20:
            reasons.append("ارتفاع تكلفة النتيجة خفّض الكفاءة العامة")

    if not reasons:
        reasons.append("لا يوجد تدهور واضح أو البيانات غير كافية لتحديد سبب حاسم")

    return {
        "comparison": comp,
        "suspected_reasons": reasons,
    }


def build_deep_root_cause(current_df: pd.DataFrame, compare_df: pd.DataFrame) -> Dict[str, Any]:
    comp = build_period_comparison(current_df, compare_df)
    current = comp["current"]
    previous = comp["previous"]
    drivers = []

    for metric, label in [
        ("ctr_pct", "CTR"),
        ("p75_rate_pct", "P75 retention"),
        ("click_to_result_rate_pct", "Post-click conversion"),
        ("cpl", "CPL"),
        ("result_rate_pct", "Result rate"),
    ]:
        a = current.get(metric)
        b = previous.get(metric)
        if a is None or b in (None, 0):
            continue
        delta = round(((a - b) / b) * 100, 2)
        drivers.append({"metric": label, "delta_pct": delta, "current": a, "previous": b})

    drivers = sorted(drivers, key=lambda x: abs(x["delta_pct"]), reverse=True)

    interpretation = []
    for item in drivers[:3]:
        if item["metric"] == "Post-click conversion" and item["delta_pct"] < 0:
            interpretation.append("المشكلة الأساسية بعد النقر: الفورم أو نية الجمهور أو العرض.")
        elif item["metric"] == "CTR" and item["delta_pct"] < 0:
            interpretation.append("الضعف الأقرب في الإبداع أو الاستهداف أو الهوك.")
        elif item["metric"] == "P75 retention" and item["delta_pct"] < 0:
            interpretation.append("الانخفاض بدأ من جودة المشاهدة والاهتمام بالفيديو.")
        elif item["metric"] == "CPL" and item["delta_pct"] > 0:
            interpretation.append("الكفاءة المالية تدهورت بوضوح بسبب ارتفاع تكلفة النتيجة.")

    if not interpretation:
        interpretation.append("لا يوجد driver واحد حاسم؛ التراجع موزع على أكثر من طبقة.")

    return {
        "comparison": comp,
        "drivers": drivers[:5],
        "interpretation": interpretation,
    }
