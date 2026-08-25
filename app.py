from __future__ import annotations

import asyncio
import email.utils
import html
import json
import mimetypes
import os
import re
import ssl
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time as clock_time, timedelta, timezone
from html.parser import HTMLParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = ImageDraw = ImageFont = None


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
TEMPLATE_PATH = BASE_DIR / "templates" / "index.html"
FRONTEND_DIST_DIR = BASE_DIR / "frontend" / "dist"
FRONTEND_INDEX_PATH = FRONTEND_DIST_DIR / "index.html"

TAIFEX_CALLS_PUTS_URL = "https://www.taifex.com.tw/cht/3/callsAndPutsDate"
TAIFEX_FUT_CONTRACTS_URL = "https://www.taifex.com.tw/cht/3/futContractsDate"
TAIFEX_FUT_DAILY_URL = "https://www.taifex.com.tw/cht/3/futDailyMarketReport"
TAIFEX_LARGE_TRADER_URL = "https://www.taifex.com.tw/cht/3/largeTraderFutQry"
TAIFEX_PC_RATIO_URL = "https://www.taifex.com.tw/cht/3/pcRatio"
TWSE_MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TWSE_T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
TWSE_BFI82U_URL = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"

PRODUCT_ID = "TXO"
PRODUCT_NAME = "臺指選擇權"
FUTURES_PRODUCT_ID = "TXF"
FUTURES_PRODUCT_NAME = "臺股期貨"
FUTURES_COMBO_NAME = "臺股期貨(TX+MTX/4+TMF/20)"
MINI_FUTURES_DAILY_ID = "MTX"
MINI_FUTURES_INSTITUTIONAL_ID = "MXF"
MINI_FUTURES_PRODUCT_NAME = "小型臺指期貨"
LOOKBACK_ROWS = int(os.getenv("LOOKBACK_ROWS", "30"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.25"))
DEFAULT_HOST = os.getenv("HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("PORT", "8080"))
APP_BASE_URL = os.getenv("APP_BASE_URL", f"http://{DEFAULT_HOST}:{DEFAULT_PORT}")
TIMEZONE_NAME = os.getenv("TIMEZONE", "Asia/Taipei")
SCHEDULE_TIME = os.getenv("SCHEDULE_TIME", "16:20")
RUN_ON_STARTUP = os.getenv("RUN_ON_STARTUP", "1") == "1"
DISCORD_API_BASE = "https://discord.com/api/v10"
OPTION_IMBALANCE_THRESHOLD = float(os.getenv("OPTION_IMBALANCE_THRESHOLD", "0.05"))
OPTION_STRONG_IMBALANCE_THRESHOLD = float(os.getenv("OPTION_STRONG_IMBALANCE_THRESHOLD", "0.15"))


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_json_env(path: Path) -> None:
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    for key, value in data.items():
        env_key = key.upper()
        if isinstance(value, (list, dict)):
            os.environ.setdefault(env_key, json.dumps(value, ensure_ascii=False))
        else:
            os.environ.setdefault(env_key, str(value))


load_dotenv(BASE_DIR / ".env")
load_json_env(BASE_DIR / "discord_config.json")

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
if DISCORD_BOT_TOKEN.lower().startswith("bot "):
    DISCORD_BOT_TOKEN = DISCORD_BOT_TOKEN[4:].strip()
DISCORD_SEND_AFTER_REFRESH = os.getenv("DISCORD_SEND_AFTER_REFRESH", "1") == "1"
DISCORD_BOT_ENABLED = os.getenv("DISCORD_BOT_ENABLED", "1") == "1"


def parse_discord_channel_ids() -> list[int]:
    values: list[Any] = []
    multi = (os.getenv("DISCORD_CHANNEL_IDS", "") or "").strip()
    single = (os.getenv("DISCORD_CHANNEL_ID", "") or "").strip()
    if multi:
        try:
            parsed = json.loads(multi)
            values.extend(parsed if isinstance(parsed, list) else [parsed])
        except json.JSONDecodeError:
            values.extend(part.strip() for part in multi.split(","))
    if single:
        values.append(single)

    ids: list[int] = []
    for value in values:
        try:
            channel_id = int(str(value).strip().strip('"').strip("'"))
        except ValueError:
            continue
        if channel_id and channel_id not in ids:
            ids.append(channel_id)
    return ids


DISCORD_CHANNEL_IDS = parse_discord_channel_ids()
IDENTITY_LABELS = {"foreign": "外資", "investmentTrust": "投信", "dealer": "自營商"}
IDENTITY_KEYS = {value: key for key, value in IDENTITY_LABELS.items()}
IDENTITY_ORDER = ["foreign", "investmentTrust", "dealer"]
CATEGORY_LABELS = {
    "overview": "總覽",
    "cash": "現貨",
    "futures": "期貨",
    "options": "選擇權",
}


def now_taipei() -> datetime:
    try:
        tz = ZoneInfo(TIMEZONE_NAME)
    except ZoneInfoNotFoundError:
        tz = timezone(timedelta(hours=8), name="Asia/Taipei")
    return datetime.now(tz)


def parse_schedule_time(value: str) -> clock_time:
    hour, minute = value.split(":", 1)
    return clock_time(int(hour), int(minute))


def is_weekday(moment: datetime) -> bool:
    """Return True from Monday through Friday in the supplied timezone."""
    return moment.weekday() < 5


def should_run_daily_schedule(moment: datetime, scheduled_at: clock_time, last_run: str | None) -> bool:
    """Run once after the configured time, excluding Saturday and Sunday."""
    return (
        is_weekday(moment)
        and moment.time() >= scheduled_at
        and last_run != moment.strftime("%Y-%m-%d")
    )


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    STATIC_DIR.mkdir(exist_ok=True)


def safe_number(value: Any, default: float = 0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"<[^>]+>", "", str(value))
    text = text.replace(",", "").replace("%", "").strip()
    if not text or text in {"-", "--"}:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def as_int(value: Any) -> int:
    return int(round(safe_number(value)))


def fmt_int(value: Any) -> str:
    return f"{as_int(value):,}"


def fmt_signed_int(value: Any) -> str:
    number = as_int(value)
    return f"{'+' if number > 0 else ''}{number:,}"


def fmt_float(value: Any, digits: int = 2) -> str:
    return f"{safe_number(value):,.{digits}f}"


def fmt_signed_float(value: Any, digits: int = 2) -> str:
    number = safe_number(value)
    return f"{'+' if number > 0 else ''}{number:,.{digits}f}"


def fmt_percent(value: Any, digits: int = 2) -> str:
    return f"{safe_number(value):,.{digits}f}%"


def fmt_signed_percent(value: Any, digits: int = 2) -> str:
    return f"{fmt_signed_float(value, digits)}%"


def fmt_yi_amount(value: Any, digits: int = 2, signed: bool = False) -> str:
    amount = safe_number(value) / 100_000_000
    sign = "+" if signed and amount > 0 else ""
    return f"{sign}{amount:,.{digits}f}\u5104"


def signal_label(signal: str) -> str:
    return {
        "strong_bull": "強偏多",
        "bull": "偏多",
        "neutral": "中性",
        "bear": "偏空",
        "strong_bear": "強偏空",
        "divergent": "分歧",
    }.get(signal, "中性")


def signal_direction(signal: str) -> str:
    if signal in {"strong_bull", "bull"}:
        return "bull"
    if signal in {"strong_bear", "bear"}:
        return "bear"
    if signal == "divergent":
        return "divergent"
    return "neutral"


def classify_foreign_spot(amount: Any) -> dict[str, Any]:
    if amount is None:
        return {
            "signal": "neutral",
            "direction": "neutral",
            "label": signal_label("neutral"),
            "reason": "外資現貨缺資料",
        }
    yi_amount = safe_number(amount) / 100_000_000
    if yi_amount >= 300:
        signal = "strong_bull"
    elif yi_amount >= 100:
        signal = "bull"
    elif yi_amount <= -300:
        signal = "strong_bear"
    elif yi_amount <= -100:
        signal = "bear"
    else:
        signal = "neutral"
    return {
        "signal": signal,
        "direction": signal_direction(signal),
        "label": signal_label(signal),
        "reason": f"外資現貨 {fmt_yi_amount(amount, signed=True)}",
    }


def classify_large_traders(large: dict[str, Any]) -> dict[str, Any]:
    if "top5Net" not in large and "top10Net" not in large:
        return {
            "signal": "neutral",
            "direction": "neutral",
            "label": signal_label("neutral"),
            "reason": "大額交易人缺資料",
            "top5Signal": "neutral",
            "top10Signal": "neutral",
        }
    top5 = safe_number(large.get("top5Net"))
    top10 = safe_number(large.get("top10Net"))

    def classify_top5(value: float) -> str:
        if value > 3000:
            return "bull"
        if value < -3000:
            return "bear"
        return "neutral"

    def classify_top10(value: float) -> str:
        if value > 8000:
            return "strong_bull"
        if value < -8000:
            return "strong_bear"
        if value > 3000:
            return "bull"
        if value < -3000:
            return "bear"
        return "neutral"

    top5_signal = classify_top5(top5)
    top10_signal = classify_top10(top10)
    top5_dir = signal_direction(top5_signal)
    top10_dir = signal_direction(top10_signal)
    divergent = top5_dir in {"bull", "bear"} and top10_dir in {"bull", "bear"} and top5_dir != top10_dir

    if divergent:
        signal = "divergent"
        reason = f"大戶分歧，前五大 {fmt_signed_int(top5)}、前十大 {fmt_signed_int(top10)}"
    elif top10_dir in {"bull", "bear"}:
        signal = top10_signal
        reason = f"前十大 {fmt_signed_int(top10)}，前五大 {fmt_signed_int(top5)}"
    elif top5_dir in {"bull", "bear"}:
        signal = top5_signal
        reason = f"前五大 {fmt_signed_int(top5)}，前十大 {fmt_signed_int(top10)}"
    else:
        signal = "neutral"
        reason = f"前五大 {fmt_signed_int(top5)}、前十大 {fmt_signed_int(top10)}"

    return {
        "signal": signal,
        "direction": signal_direction(signal),
        "label": "大戶分歧" if divergent else signal_label(signal),
        "reason": reason,
        "top5Signal": top5_signal,
        "top10Signal": top10_signal,
    }


def classify_pcr(pcr: dict[str, Any]) -> dict[str, Any]:
    if "volumePcr" not in pcr and "openInterestPcr" not in pcr:
        return {
            "signal": "neutral",
            "direction": "neutral",
            "label": signal_label("neutral"),
            "reason": "PCR 缺資料",
        }
    volume_pcr = safe_number(pcr.get("volumePcr"))
    oi_pcr = safe_number(pcr.get("openInterestPcr"))
    signal = "neutral"
    reason = f"OI PCR {fmt_percent(oi_pcr)}、成交量 PCR {fmt_percent(volume_pcr)}"
    if oi_pcr >= 130:
        signal = "strong_bear"
        reason = f"OI PCR {fmt_percent(oi_pcr)} 避險重"
    elif oi_pcr >= 115:
        signal = "bear"
        reason = f"OI PCR {fmt_percent(oi_pcr)} 偏高"
    elif oi_pcr <= 90 and oi_pcr > 0:
        signal = "bull"
        reason = f"OI PCR {fmt_percent(oi_pcr)} 偏低"
    elif volume_pcr >= 120:
        signal = "bear"
        reason = f"成交量 PCR {fmt_percent(volume_pcr)} 偏高"
    elif volume_pcr <= 80 and volume_pcr > 0:
        signal = "bull"
        reason = f"成交量 PCR {fmt_percent(volume_pcr)} 偏低"
    return {
        "signal": signal,
        "direction": signal_direction(signal),
        "label": signal_label(signal),
        "reason": reason,
    }


def classify_foreign_option_amount(amount: Any) -> dict[str, Any]:
    if amount is None:
        return {
            "signal": "neutral",
            "direction": "neutral",
            "label": signal_label("neutral"),
            "reason": "外資選擇權金額缺資料",
        }
    value = safe_number(amount)
    if value >= 200000:
        signal = "strong_bull"
    elif value >= 50000:
        signal = "bull"
    elif value <= -200000:
        signal = "strong_bear"
    elif value <= -50000:
        signal = "bear"
    else:
        signal = "neutral"
    return {
        "signal": signal,
        "direction": signal_direction(signal),
        "label": signal_label(signal),
        "reason": f"外資選擇權金額 {fmt_signed_int(value)}",
    }


def classify_option_imbalance(bull_value: Any, bear_value: Any, metric_name: str) -> dict[str, Any]:
    """Classify a bullish/bearish option balance on a scale normalized by total positions."""
    if bull_value is None and bear_value is None:
        return {
            "signal": "neutral",
            "direction": "neutral",
            "label": signal_label("neutral"),
            "net": 0,
            "imbalanceRatio": 0,
            "imbalanceRatioFormat": "0.00%",
            "reason": f"{metric_name}缺資料",
        }

    bull = max(safe_number(bull_value), 0)
    bear = max(safe_number(bear_value), 0)
    total = bull + bear
    net = bull - bear
    ratio = net / total if total else 0
    if ratio >= OPTION_STRONG_IMBALANCE_THRESHOLD:
        signal = "strong_bull"
    elif ratio >= OPTION_IMBALANCE_THRESHOLD:
        signal = "bull"
    elif ratio <= -OPTION_STRONG_IMBALANCE_THRESHOLD:
        signal = "strong_bear"
    elif ratio <= -OPTION_IMBALANCE_THRESHOLD:
        signal = "bear"
    else:
        signal = "neutral"
    return {
        "signal": signal,
        "direction": signal_direction(signal),
        "label": signal_label(signal),
        "bull": as_int(bull),
        "bear": as_int(bear),
        "net": as_int(net),
        "imbalanceRatio": round(ratio, 4),
        "imbalanceRatioFormat": fmt_signed_percent(ratio * 100),
        "reason": (
            f"{metric_name}{signal_label(signal)}"
            f"（偏多 {fmt_int(bull)} / 偏空 {fmt_int(bear)}，"
            f"差 {fmt_signed_int(net)}、{fmt_signed_percent(ratio * 100)}）"
        ),
    }


def classify_foreign_options(foreign_amount: dict[str, Any], foreign_lots: dict[str, Any]) -> dict[str, Any]:
    """Combine option amount and lot balances using TAIFEX's four-leg directional grouping."""
    amount_view = classify_option_imbalance(
        foreign_amount.get("bullAmount"),
        foreign_amount.get("bearAmount"),
        "選擇權金額",
    )
    lot_view = classify_option_imbalance(
        foreign_lots.get("bullLot"),
        foreign_lots.get("bearLot"),
        "選淨額口數",
    )
    amount_direction = amount_view["direction"]
    lot_direction = lot_view["direction"]
    directional = {"bull", "bear"}

    if amount_direction in directional and lot_direction in directional and amount_direction != lot_direction:
        signal = "divergent"
        label = "金額口數分歧"
    elif amount_direction in directional and amount_direction == lot_direction:
        strong_signal = f"strong_{amount_direction}"
        signal = strong_signal if amount_view["signal"] == strong_signal and lot_view["signal"] == strong_signal else amount_direction
        label = signal_label(signal)
    elif amount_direction in directional:
        signal = amount_direction
        label = signal_label(signal)
    elif lot_direction in directional:
        signal = lot_direction
        label = signal_label(signal)
    else:
        signal = "neutral"
        label = signal_label(signal)

    direction = signal_direction(signal)
    return {
        "signal": signal,
        "direction": direction,
        "score": 1 if direction == "bull" else -1 if direction == "bear" else 0,
        "label": label,
        "reason": f"{amount_view['reason']}；{lot_view['reason']}",
        "amount": amount_view,
        "netLot": lot_view,
        "strategyRule": {
            "bull": "Buy Call（看大漲）＋Sell Put（看不跌）",
            "bear": "Buy Put（看大跌）＋Sell Call（看不漲）",
        },
    }


def build_option_position_views(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    institutional_amounts = row.get("optionInstitutionalAmount") or {}
    institutional_lots = row.get("txoInstitutionalOpenInterest") or {}
    views: dict[str, dict[str, Any]] = {}
    for identity in IDENTITY_ORDER:
        amount = institutional_amounts.get(identity) or {}
        if identity == "foreign" and not amount:
            amount = row.get("foreignOptionAmount") or {}
        views[identity] = classify_foreign_options(amount, institutional_lots.get(identity) or {})
    return views


def build_foreign_position_view(row: dict[str, Any]) -> dict[str, Any]:
    spot = row.get("spotInstitutional") or {}
    large = row.get("largeTraderFutures") or {}
    pcr = row.get("optionPcr") or {}
    institutional_amounts = row.get("optionInstitutionalAmount") or {}
    foreign_opt = institutional_amounts.get("foreign") or row.get("foreignOptionAmount") or {}
    foreign_option_lots = ((row.get("txoInstitutionalOpenInterest") or {}).get("foreign") or {})

    signals = {
        "spot": classify_foreign_spot(spot.get("foreignNetBuyAmount")),
        "largeTrader": classify_large_traders(large),
        "pcr": classify_pcr(pcr),
        "foreignOption": classify_foreign_options(foreign_opt, foreign_option_lots),
    }
    directions = {key: item["direction"] for key, item in signals.items()}
    bull_count = sum(1 for value in directions.values() if value == "bull")
    bear_count = sum(1 for value in directions.values() if value == "bear")
    derivative_bull_count = sum(1 for key in ("largeTrader", "pcr", "foreignOption") if directions[key] == "bull")
    derivative_bear_count = sum(1 for key in ("largeTrader", "pcr", "foreignOption") if directions[key] == "bear")
    has_divergence = any(directions[key] == "divergent" for key in ("largeTrader", "foreignOption"))
    balance_score = bull_count - bear_count

    if bull_count >= 3 and directions["pcr"] != "bear":
        bias = "bullish"
        label = "外資偏多"
        score = balance_score
        explanation = "外資現貨、期貨大戶與選擇權多數偏多"
    elif bear_count >= 3:
        bias = "bearish"
        label = "外資偏空"
        score = balance_score
        explanation = "外資現貨、期貨大戶、PCR 或選擇權多數偏空"
    elif (directions["spot"] == "bull" and derivative_bear_count >= 2) or (directions["spot"] == "bear" and derivative_bull_count >= 2) or has_divergence:
        bias = "hedged"
        label = "外資偏對沖"
        score = 0
        explanation = "現貨與衍生性商品方向不一致"
    else:
        bias = "neutral"
        label = "中性 / 訊號不足"
        score = 0
        explanation = "多空訊號未達確認門檻"

    reasons = [
        signals["spot"]["reason"],
        signals["largeTrader"]["reason"],
        signals["pcr"]["reason"],
        signals["foreignOption"]["reason"],
    ]
    explanation_lines = [
        f"多空強度：{'高' if max(bull_count, bear_count) >= 3 else '中' if max(bull_count, bear_count) == 2 else '低'}（多方 {bull_count} 項 / 空方 {bear_count} 項）"
    ]
    if bias == "bullish":
        explanation_lines.append(f"偏多原因：{explanation}")
    elif bias == "bearish":
        explanation_lines.append(f"偏空原因：{explanation}")
    elif bias == "hedged":
        explanation_lines.append("可能為避險：現貨與期貨/選擇權方向不一致")
    else:
        explanation_lines.append("目前多空訊號不夠一致，先視為中性。")
    if signals["pcr"]["direction"] == "bear":
        explanation_lines.append(f"避險訊號：{signals['pcr']['reason']}，Put 避險壓力較重")
    explanation_lines.append(
        "選擇權口徑：偏多 = Buy Call（看大漲）＋Sell Put（看不跌）；"
        "偏空 = Buy Put（看大跌）＋Sell Call（看不漲）"
    )
    explanation_lines.append("注意：法人資料是外資群體合計互抵結果，不代表單一外資機構的完整策略。")
    return {
        "label": label,
        "bias": bias,
        "score": score,
        "scoreFormat": fmt_signed_int(score),
        "balanceScore": balance_score,
        "balanceScoreFormat": fmt_signed_int(balance_score),
        "bullCount": bull_count,
        "bearCount": bear_count,
        "confidence": "高" if max(bull_count, bear_count) >= 3 else "中" if max(bull_count, bear_count) == 2 else "低",
        "summary": explanation,
        "reason": " + ".join(reasons),
        "explanationLines": explanation_lines,
        "explanation": "；".join(explanation_lines),
        "signals": signals,
    }


def parse_taifex_date(value: str) -> date:
    return datetime.strptime(value.strip(), "%Y/%m/%d").date()


def parse_twse_date(value: str) -> date:
    year_text, month_text, day_text = value.strip().split("/")
    year = int(year_text)
    if year < 1911:
        year += 1911
    return date(year, int(month_text), int(day_text))


def date_label(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def taifex_date(value: date) -> str:
    return value.strftime("%Y/%m/%d")


def twse_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def value_tone(value: Any) -> str:
    number = safe_number(value)
    if number > 0:
        return "positive"
    if number < 0:
        return "negative"
    return "neutral"


def first_parenthetical_number(value: str) -> int:
    text = str(value)
    match = re.search(r"-?[\d,]+", text)
    return as_int(match.group(0)) if match else 0


def first_percent(value: str) -> float:
    text = str(value)
    match = re.search(r"-?[\d,.]+", text)
    return round(safe_number(match.group(0)), 2) if match else 0


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._in_row = False
        self._in_cell = False
        self._cells: list[str] = []
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._in_row = True
            self._cells = []
        elif self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._in_cell and tag in {"td", "th"}:
            text = html.unescape("".join(self._buffer))
            self._cells.append(" ".join(text.split()))
            self._in_cell = False
        elif self._in_row and tag == "tr":
            if self._cells:
                self.rows.append(self._cells)
            self._in_row = False


class WebClient:
    def __init__(self) -> None:
        self.opener = urllib.request.build_opener()
        self.insecure_opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl._create_unverified_context())
        )

    def headers(self, referer: str = "") -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
            "Accept": "text/html,application/json,text/plain,*/*",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": referer,
        }

    def get_text(self, url: str, referer: str = "") -> str:
        req = urllib.request.Request(url, headers=self.headers(referer))
        try:
            with self.opener.open(req, timeout=30) as response:
                return response.read().decode("utf-8-sig", errors="replace")
        except urllib.error.URLError as exc:
            if isinstance(getattr(exc, "reason", None), ssl.SSLError):
                with self.insecure_opener.open(req, timeout=30) as response:
                    return response.read().decode("utf-8-sig", errors="replace")
            raise

    def post_text(self, url: str, form: dict[str, str], referer: str = "") -> str:
        headers = self.headers(referer or url)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urllib.parse.urlencode(form).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers)
        with self.insecure_opener.open(req, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")

    def get_json(self, url: str, referer: str = "") -> dict[str, Any]:
        return json.loads(self.get_text(url, referer))


@dataclass
class OptionSide:
    oi_buy_lot: int = 0
    oi_buy_amount: int = 0
    oi_sell_lot: int = 0
    oi_sell_amount: int = 0


class OptionInstitutionalClient(WebClient):
    def latest_trade_date(self) -> date:
        text = self.get_text(TAIFEX_CALLS_PUTS_URL)
        return extract_display_date(text)

    def fetch_day(self, day: date) -> dict[str, Any] | None:
        text = self.post_text(
            TAIFEX_CALLS_PUTS_URL,
            {"queryDate": taifex_date(day), "commodityId": PRODUCT_ID, "queryType": "", "goDay": "", "doQuery": "1", "dateaddcnt": ""},
        )
        try:
            displayed_date = extract_display_date(text)
        except ValueError:
            return None
        if displayed_date != day:
            return None
        try:
            return parse_option_institutional(text, day)
        except ValueError:
            return None

    def fetch_history(self, limit: int = LOOKBACK_ROWS) -> list[dict[str, Any]]:
        latest = self.latest_trade_date()
        rows: list[dict[str, Any]] = []
        cursor = latest
        misses = 0
        while len(rows) < limit and misses <= limit * 4:
            try:
                row = self.fetch_day(cursor)
            except Exception:
                row = None
            if row:
                rows.append(row)
            cursor -= timedelta(days=1)
            misses += 1
            time.sleep(REQUEST_DELAY)
        rows.sort(key=lambda item: item["date"], reverse=True)
        return rows


class TwseMarketStatsClient(WebClient):
    def fetch_day(self, day: date) -> dict[str, Any] | None:
        url = f"{TWSE_MI_INDEX_URL}?{urllib.parse.urlencode({'date': twse_date(day), 'type': 'ALLBUT0999', 'response': 'json'})}"
        payload = self.get_json(url, "https://www.twse.com.tw/zh/trading/historical/mi-index.html")
        if payload.get("stat") != "OK":
            return None
        close = change = change_percent = listed_volume = listed_amount = 0
        for table in payload.get("tables") or []:
            title = table.get("title") or ""
            if "價格指數" in title and "臺灣證券交易所" in title:
                for cells in table.get("data") or []:
                    if cells and cells[0] == "發行量加權股價指數":
                        close = safe_number(cells[1])
                        sign = -1 if "-" in str(cells[2]) else 1
                        change = abs(safe_number(cells[3])) * sign
                        change_percent = abs(safe_number(cells[4])) * sign
            if "大盤統計資訊" in title:
                for cells in table.get("data") or []:
                    if cells and "一般股票" in str(cells[0]):
                        listed_amount = as_int(cells[1])
                        listed_volume = as_int(cells[2])
        if not close:
            return None
        return {
            "taiexClose": round(close, 2),
            "taiexChange": round(change, 2),
            "taiexChangePercent": round(change_percent, 2),
            "listedVolume": listed_volume,
            "listedAmount": listed_amount,
            "taiexCloseFormat": fmt_float(close),
            "taiexChangeFormat": fmt_signed_float(change),
            "taiexChangePercentFormat": fmt_signed_percent(change_percent),
            "listedVolumeFormat": fmt_int(listed_volume),
            "listedAmountFormat": fmt_int(listed_amount),
            "listedAmountYiFormat": fmt_yi_amount(listed_amount),
        }


class TwseInstitutionalClient(WebClient):
    def fetch_day(self, day: date) -> dict[str, Any] | None:
        url = f"{TWSE_BFI82U_URL}?{urllib.parse.urlencode({'dayDate': twse_date(day), 'type': 'day', 'response': 'json'})}"
        payload = self.get_json(url, "https://www.twse.com.tw/zh/trading/foreign/bfi82u.html")
        if payload.get("stat") != "OK":
            return None
        totals = {"foreignNetBuyAmount": 0, "investmentTrustNetBuyAmount": 0, "dealerNetBuyAmount": 0}
        for cells in payload.get("data") or []:
            if len(cells) < 4:
                continue
            label = str(cells[0])
            amount = as_int(cells[3])
            if "外資及陸資" in label or "外資自營商" in label:
                totals["foreignNetBuyAmount"] += amount
            elif label == "投信":
                totals["investmentTrustNetBuyAmount"] += amount
            elif "自營商" in label:
                totals["dealerNetBuyAmount"] += amount
        for key, value in list(totals.items()):
            totals[f"{key}Format"] = fmt_signed_int(value)
            totals[f"{key}YiFormat"] = fmt_yi_amount(value, signed=True)
        return totals


class FuturesInstitutionalClient(WebClient):
    def fetch_day(
        self,
        day: date,
        product_id: str = FUTURES_PRODUCT_ID,
        product_name: str = FUTURES_PRODUCT_NAME,
    ) -> dict[str, Any] | None:
        text = self.post_text(
            TAIFEX_FUT_CONTRACTS_URL,
            {"queryDate": taifex_date(day), "commodityId": product_id, "queryType": "", "goDay": "", "doQuery": "1", "dateaddcnt": ""},
        )
        try:
            if extract_display_date(text) != day:
                return None
        except ValueError:
            return None
        parser = TableParser()
        parser.feed(text)
        values: dict[str, Any] = {}
        current_product = ""
        for cells in parser.rows:
            if len(cells) >= 15 and cells[0].isdigit():
                current_product = cells[1]
                identity_label = cells[2]
                numbers = cells[3:]
            elif len(cells) >= 13 and cells[0] in IDENTITY_KEYS:
                identity_label = cells[0]
                numbers = cells[1:]
            else:
                continue
            if current_product != product_name:
                continue
            identity = IDENTITY_KEYS.get(identity_label)
            if not identity or len(numbers) < 12:
                continue
            long_lot = as_int(numbers[6])
            short_lot = as_int(numbers[8])
            net_lot = as_int(numbers[10])
            values[identity] = {
                "long": long_lot,
                "short": short_lot,
                "net": net_lot,
                "longFormat": fmt_int(long_lot),
                "shortFormat": fmt_int(short_lot),
                "netFormat": fmt_signed_int(net_lot),
            }
        return values or None


class MiniRetailFuturesClient(WebClient):
    def __init__(self, institutional_client: FuturesInstitutionalClient) -> None:
        super().__init__()
        self.institutional_client = institutional_client

    def fetch_total_open_interest(self, day: date) -> int | None:
        text = self.post_text(
            TAIFEX_FUT_DAILY_URL,
            {
                "queryDate": taifex_date(day),
                "MarketCode": "0",
                "commodity_idt": MINI_FUTURES_DAILY_ID,
                "commodity_id": MINI_FUTURES_DAILY_ID,
                "commodity_id2": "",
                "commodity_id2t": "",
                "commodity_id2t2": "",
                "queryType": "",
                "dateaddcnt": "",
                "button": "送出查詢",
            },
            TAIFEX_FUT_DAILY_URL,
        )
        try:
            if extract_display_date(text) != day:
                return None
        except ValueError:
            return None
        parser = TableParser()
        parser.feed(text)
        total = 0
        for cells in parser.rows:
            if len(cells) >= 13 and cells[0] == MINI_FUTURES_DAILY_ID and "/" not in cells[1]:
                total += as_int(cells[12])
        return total or None

    def fetch_day(self, day: date) -> dict[str, Any] | None:
        total_open_interest = self.fetch_total_open_interest(day)
        institutional = self.institutional_client.fetch_day(
            day,
            product_id=MINI_FUTURES_INSTITUTIONAL_ID,
            product_name=MINI_FUTURES_PRODUCT_NAME,
        )
        if not total_open_interest or not institutional:
            return None
        institutional_long = sum(as_int(item.get("long")) for item in institutional.values())
        institutional_short = sum(as_int(item.get("short")) for item in institutional.values())
        institutional_net = institutional_long - institutional_short
        retail_position = -1 * institutional_net
        ratio = round(retail_position / total_open_interest * 100, 2) if total_open_interest else 0
        result = {
            "totalOpenInterest": total_open_interest,
            "institutionalLong": institutional_long,
            "institutionalShort": institutional_short,
            "institutionalNet": institutional_net,
            "retailPosition": retail_position,
            "retailLongShortRatio": ratio,
            "bias": "long" if ratio > 0 else "short" if ratio < 0 else "neutral",
        }
        result.update({
            "totalOpenInterestFormat": fmt_int(total_open_interest),
            "institutionalLongFormat": fmt_int(institutional_long),
            "institutionalShortFormat": fmt_int(institutional_short),
            "institutionalNetFormat": fmt_signed_int(institutional_net),
            "retailPositionFormat": fmt_signed_int(retail_position),
            "retailLongShortRatioFormat": fmt_signed_percent(ratio),
        })
        return result


class LargeTraderClient(WebClient):
    def fetch_day(self, day: date) -> dict[str, Any] | None:
        text = self.post_text(
            TAIFEX_LARGE_TRADER_URL,
            {"queryDate": taifex_date(day), "contractId": "TX", "contractId2": "", "datecount": ""},
        )
        try:
            if extract_display_date(text) != day:
                return None
        except ValueError:
            return None
        parser = TableParser()
        parser.feed(text)
        current_product = ""
        for cells in parser.rows:
            if not cells:
                continue
            row = list(cells)
            if row[0].startswith("臺股期貨"):
                current_product = row[0]
                row = row[1:]
            if current_product.startswith(FUTURES_COMBO_NAME) and len(row) >= 10 and row[0] == "所有契約":
                result = {
                    "contractScope": row[0],
                    "top5Long": first_parenthetical_number(row[1]),
                    "top5LongPercent": first_percent(row[2]),
                    "top10Long": first_parenthetical_number(row[3]),
                    "top10LongPercent": first_percent(row[4]),
                    "top5Short": first_parenthetical_number(row[5]),
                    "top5ShortPercent": first_percent(row[6]),
                    "top10Short": first_parenthetical_number(row[7]),
                    "top10ShortPercent": first_percent(row[8]),
                    "marketOpenInterest": as_int(row[9]),
                }
                result["top5Net"] = result["top5Long"] - result["top5Short"]
                result["top10Net"] = result["top10Long"] - result["top10Short"]
                result["top5Bias"] = "long" if result["top5Net"] > 0 else "short" if result["top5Net"] < 0 else "neutral"
                result["top10Bias"] = "long" if result["top10Net"] > 0 else "short" if result["top10Net"] < 0 else "neutral"
                for key, value in list(result.items()):
                    if isinstance(value, (int, float)):
                        result[f"{key}Format"] = fmt_percent(value) if key.endswith("Percent") else fmt_signed_int(value) if key.endswith("Net") else fmt_int(value)
                return result
        return None


class PcRatioClient(WebClient):
    def fetch_history(self) -> dict[str, dict[str, Any]]:
        text = self.get_text(TAIFEX_PC_RATIO_URL)
        parser = TableParser()
        parser.feed(text)
        rows: dict[str, dict[str, Any]] = {}
        for cells in parser.rows:
            if len(cells) < 7 or "/" not in cells[0]:
                continue
            try:
                day = parse_taifex_date(cells[0])
            except ValueError:
                continue
            row = {
                "putVolume": as_int(cells[1]),
                "callVolume": as_int(cells[2]),
                "volumePcr": round(safe_number(cells[3]), 2),
                "putOpenInterest": as_int(cells[4]),
                "callOpenInterest": as_int(cells[5]),
                "openInterestPcr": round(safe_number(cells[6]), 2),
            }
            row.update({
                "putVolumeFormat": fmt_int(row["putVolume"]),
                "callVolumeFormat": fmt_int(row["callVolume"]),
                "volumePcrFormat": fmt_percent(row["volumePcr"]),
                "putOpenInterestFormat": fmt_int(row["putOpenInterest"]),
                "callOpenInterestFormat": fmt_int(row["callOpenInterest"]),
                "openInterestPcrFormat": fmt_percent(row["openInterestPcr"]),
            })
            rows[date_label(day)] = row
        return rows


def extract_display_date(text: str) -> date:
    match = re.search(r"(\d{4}/\d{2}/\d{2})", text)
    if not match:
        raise ValueError("page did not include a data date")
    return parse_taifex_date(match.group(1))


def parse_option_institutional(text: str, trade_date: date) -> dict[str, Any]:
    parser = TableParser()
    parser.feed(text)
    raw: dict[str, dict[str, OptionSide]] = {key: {"買權": OptionSide(), "賣權": OptionSide()} for key in IDENTITY_ORDER}
    current_product = ""
    current_option = ""
    for cells in parser.rows:
        if not cells:
            continue
        if cells[0].isdigit() and len(cells) >= 16:
            current_product, current_option, identity_label, numbers = cells[1], cells[2], cells[3], cells[4:]
        elif cells[0] in {"買權", "賣權"} and len(cells) >= 14:
            current_option, identity_label, numbers = cells[0], cells[1], cells[2:]
        elif cells[0] in IDENTITY_KEYS and len(cells) >= 13:
            identity_label, numbers = cells[0], cells[1:]
        else:
            continue
        if current_product != PRODUCT_NAME or current_option not in {"買權", "賣權"}:
            continue
        identity = IDENTITY_KEYS.get(identity_label)
        if not identity or len(numbers) < 10:
            continue
        raw[identity][current_option] = OptionSide(
            oi_buy_lot=as_int(numbers[6]),
            oi_buy_amount=as_int(numbers[7]),
            oi_sell_lot=as_int(numbers[8]),
            oi_sell_amount=as_int(numbers[9]),
        )
    txo: dict[str, Any] = {}
    option_amounts: dict[str, Any] = {}
    for identity in IDENTITY_ORDER:
        call = raw[identity]["買權"]
        put = raw[identity]["賣權"]
        bull_lot = call.oi_buy_lot + put.oi_sell_lot
        bear_lot = put.oi_buy_lot + call.oi_sell_lot
        net_lot = bull_lot - bear_lot
        bull_amount = call.oi_buy_amount + put.oi_sell_amount
        bear_amount = put.oi_buy_amount + call.oi_sell_amount
        net_amount = bull_amount - bear_amount
        txo[identity] = {
            "bullLot": bull_lot,
            "bearLot": bear_lot,
            "netLot": net_lot,
            "bullLotFormat": fmt_int(bull_lot),
            "bearLotFormat": fmt_int(bear_lot),
            "netLotFormat": fmt_signed_int(net_lot),
            "buyCallLot": call.oi_buy_lot,
            "sellPutLot": put.oi_sell_lot,
            "buyPutLot": put.oi_buy_lot,
            "sellCallLot": call.oi_sell_lot,
        }
        option_amounts[identity] = {
            "bullAmount": bull_amount,
            "bearAmount": bear_amount,
            "netAmount": net_amount,
            "bullAmountFormat": fmt_int(bull_amount),
            "bearAmountFormat": fmt_int(bear_amount),
            "netAmountFormat": fmt_signed_int(net_amount),
            "buyCallAmount": call.oi_buy_amount,
            "sellPutAmount": put.oi_sell_amount,
            "buyPutAmount": put.oi_buy_amount,
            "sellCallAmount": call.oi_sell_amount,
        }
    if not any((txo[identity]["bullLot"] or txo[identity]["bearLot"]) for identity in IDENTITY_ORDER):
        raise ValueError(f"No {PRODUCT_NAME} rows were found.")
    return {
        "date": trade_date.isoformat(),
        "dateLabel": date_label(trade_date),
        "foreignOptionAmount": option_amounts["foreign"],
        "optionInstitutionalAmount": option_amounts,
        "txoInstitutionalOpenInterest": txo,
    }


def empty_payload(error: str | None = None) -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "source": "TWSE/TAIFEX 每日籌碼總覽",
        "sourceUrls": {
            "twseMarket": TWSE_MI_INDEX_URL,
            "twseInstitutional": TWSE_T86_URL,
            "taifexOption": TAIFEX_CALLS_PUTS_URL,
            "taifexFutures": TAIFEX_FUT_CONTRACTS_URL,
            "taifexLargeTrader": TAIFEX_LARGE_TRADER_URL,
            "taifexFuturesDaily": TAIFEX_FUT_DAILY_URL,
            "taifexPcr": TAIFEX_PC_RATIO_URL,
        },
        "rows": [],
        "latest": None,
        "fetchedAt": None,
        "lastError": error,
    }


def with_diffs(rows: list[dict[str, Any]]) -> None:
    paths = [
        ("marketIndex", "taiexClose"),
        ("marketIndex", "taiexChange"),
        ("marketIndex", "taiexChangePercent"),
        ("cashMarket", "listedVolume"),
        ("cashMarket", "listedAmount"),
        ("spotInstitutional", "foreignNetBuyAmount"),
        ("spotInstitutional", "investmentTrustNetBuyAmount"),
        ("spotInstitutional", "dealerNetBuyAmount"),
        ("largeTraderFutures", "top5Net"),
        ("largeTraderFutures", "top10Net"),
        ("retailMiniFutures", "retailLongShortRatio"),
        ("retailMiniFutures", "retailPosition"),
        ("foreignOptionAmount", "netAmount"),
        ("optionPcr", "volumePcr"),
        ("optionPcr", "openInterestPcr"),
    ]
    for index, row in enumerate(rows):
        previous = rows[index + 1] if index + 1 < len(rows) else {}
        for section, key in paths:
            current_section = row.get(section) or {}
            prev_section = previous.get(section) or {}
            if key not in current_section:
                continue
            diff = safe_number(current_section.get(key)) - safe_number(prev_section.get(key)) if prev_section else 0
            current_section[f"{key}Diff"] = round(diff, 2)
            if "Percent" in key or "Pcr" in key or "Ratio" in key:
                current_section[f"{key}DiffFormat"] = fmt_signed_float(diff)
            elif key.endswith("Amount") or key.endswith("BuyAmount") or key == "listedAmount":
                current_section[f"{key}DiffFormat"] = fmt_yi_amount(diff, signed=True)
            else:
                current_section[f"{key}DiffFormat"] = fmt_signed_int(diff)


def merge_row(base: dict[str, Any], previous: dict[str, Any] | None, section: str, value: Any) -> None:
    if value:
        base[section] = value
    elif previous and previous.get(section):
        base[section] = previous[section]
        base.setdefault("missingSources", []).append(section)
    else:
        base[section] = {}
        base.setdefault("missingSources", []).append(section)


def normalize_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 2:
        return empty_payload()
    payload.setdefault("rows", [])
    for row in payload["rows"]:
        market = row.get("marketIndex") or {}
        change = safe_number(market.get("taiexChange"))
        change_percent = safe_number(market.get("taiexChangePercent"))
        if change and change_percent and (change > 0) != (change_percent > 0):
            fixed_percent = abs(change_percent) * (1 if change > 0 else -1)
            market["taiexChangePercent"] = round(fixed_percent, 2)
            market["taiexChangePercentFormat"] = fmt_signed_percent(fixed_percent)
        row["optionPositionViews"] = build_option_position_views(row)
        row["foreignPositionView"] = build_foreign_position_view(row)
    payload["latest"] = payload.get("latest") or (payload["rows"][0] if payload["rows"] else None)
    if payload["rows"]:
        payload["latest"] = payload["rows"][0]
    return payload


class DataStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return empty_payload()
        try:
            return normalize_payload(json.loads(self.path.read_text(encoding="utf-8")))
        except Exception as exc:
            return empty_payload(str(exc))

    def save(self, payload: dict[str, Any]) -> None:
        with self.lock:
            ensure_dirs()
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)


store = DataStore(DATA_DIR / "latest.json")
option_client = OptionInstitutionalClient()
market_client = TwseMarketStatsClient()
spot_client = TwseInstitutionalClient()
futures_client = FuturesInstitutionalClient()
retail_mini_client = MiniRetailFuturesClient(futures_client)
large_trader_client = LargeTraderClient()
pcr_client = PcRatioClient()
last_error: str | None = None
last_scheduler_run: str | None = None
discord_client: Any = None


def refresh_data() -> dict[str, Any]:
    global last_error
    previous_payload = store.load()
    previous_by_date = {row.get("date"): row for row in previous_payload.get("rows") or []}
    option_rows = option_client.fetch_history(LOOKBACK_ROWS)
    pcr_by_date = pcr_client.fetch_history()
    rows: list[dict[str, Any]] = []
    errors: list[str] = []

    for option_row in option_rows:
        day = datetime.strptime(option_row["date"], "%Y-%m-%d").date()
        previous = previous_by_date.get(option_row["date"])
        row = {
            "date": option_row["date"],
            "dateLabel": option_row["dateLabel"],
            "missingSources": [],
            "foreignOptionAmount": option_row.get("foreignOptionAmount", {}),
            "optionInstitutionalAmount": option_row.get("optionInstitutionalAmount", {}),
            "txoInstitutionalOpenInterest": option_row.get("txoInstitutionalOpenInterest", {}),
        }
        fetchers = {
            "marketIndex": market_client.fetch_day,
            "spotInstitutional": spot_client.fetch_day,
            "futuresInstitutional": futures_client.fetch_day,
            "retailMiniFutures": retail_mini_client.fetch_day,
            "largeTraderFutures": large_trader_client.fetch_day,
        }
        for section, fetcher in fetchers.items():
            try:
                value = fetcher(day)
            except Exception as exc:
                value = None
                errors.append(f"{option_row['dateLabel']} {section}: {exc}")
            merge_row(row, previous, section, value)
            time.sleep(REQUEST_DELAY)
        market = row.get("marketIndex") or {}
        row["cashMarket"] = {
            "listedVolume": market.get("listedVolume", 0),
            "listedAmount": market.get("listedAmount", 0),
            "listedVolumeFormat": market.get("listedVolumeFormat", "-"),
            "listedAmountFormat": market.get("listedAmountFormat", "-"),
            "listedAmountYiFormat": market.get("listedAmountYiFormat", "-"),
        }
        merge_row(row, previous, "optionPcr", pcr_by_date.get(row["dateLabel"]))
        rows.append(row)

    rows.sort(key=lambda item: item["date"], reverse=True)
    with_diffs(rows)
    for row in rows:
        row["optionPositionViews"] = build_option_position_views(row)
        row["foreignPositionView"] = build_foreign_position_view(row)
    payload = empty_payload("\n".join(errors[:8]) if errors else None)
    payload.update({
        "rows": rows,
        "latest": rows[0] if rows else None,
        "fetchedAt": now_taipei().isoformat(timespec="seconds"),
    })
    store.save(payload)
    generate_static_files(payload)
    last_error = payload.get("lastError")
    return payload


def spark_points(rows: list[dict[str, Any]], section: str, key: str) -> list[tuple[str, float]]:
    ordered = list(reversed(rows[:LOOKBACK_ROWS]))
    return [(row.get("dateLabel", ""), safe_number((row.get(section) or {}).get(key))) for row in ordered]


def nested_number(row: dict[str, Any], path: str) -> float:
    current: Any = row
    for part in path.split("."):
        if not isinstance(current, dict):
            return 0
        current = current.get(part)
    return safe_number(current)


def draw_snapshot_chart(payload: dict[str, Any], path: Path) -> None:
    if Image is None or ImageDraw is None:
        return
    latest = payload.get("latest") or {}
    rows = payload.get("rows") or []
    width, height = 1200, 675
    img = Image.new("RGB", (width, height), "#f6f8fb")
    draw = ImageDraw.Draw(img)
    try:
        title_font = ImageFont.truetype("msjh.ttc", 34)
        metric_font = ImageFont.truetype("msjh.ttc", 30)
        label_font = ImageFont.truetype("msjh.ttc", 19)
        small_font = ImageFont.truetype("msjh.ttc", 15)
    except Exception:
        title_font = metric_font = label_font = small_font = ImageFont.load_default()

    market = latest.get("marketIndex") or {}
    cash = latest.get("cashMarket") or {}
    spot = latest.get("spotInstitutional") or {}
    futures = (latest.get("futuresInstitutional") or {}).get("foreign") or {}
    large = latest.get("largeTraderFutures") or {}
    pcr = latest.get("optionPcr") or {}
    foreign_opt = latest.get("foreignOptionAmount") or {}
    foreign_view = latest.get("foreignPositionView") or {}
    retail = latest.get("retailMiniFutures") or {}

    def color(value: Any) -> str:
        return "#111827" if safe_number(value) >= 0 else "#d92d20"

    draw.rounded_rectangle((24, 20, width - 24, height - 20), radius=12, fill="#ffffff", outline="#d7dee9")
    title = f"{latest.get('dateLabel', '-')} 每日籌碼總覽"
    draw.text((50, 38), title, fill="#111827", font=title_font)
    index_text = f"大盤 {market.get('taiexCloseFormat', '-')}  {market.get('taiexChangeFormat', '-')} / {market.get('taiexChangePercentFormat', '-')}"
    draw.text((50, 86), index_text, fill=color(market.get("taiexChange")), font=label_font)
    view_text = f"外資操作判讀 {foreign_view.get('label', '中性 / 訊號不足')}：{foreign_view.get('summary', '-')}"
    draw.text((50, 112), view_text[:62], fill=color(foreign_view.get("score")), font=small_font)

    cards = [
        ("成交金額", cash.get("listedAmountYiFormat", "-"), "上市", 0),
        ("外資買賣超", spot.get("foreignNetBuyAmountYiFormat", "-"), "上市", spot.get("foreignNetBuyAmount")),
        ("投信買賣超", spot.get("investmentTrustNetBuyAmountYiFormat", "-"), "上市", spot.get("investmentTrustNetBuyAmount")),
        ("自營商買賣超", spot.get("dealerNetBuyAmountYiFormat", "-"), "上市", spot.get("dealerNetBuyAmount")),
        ("外資期貨淨額", futures.get("netFormat", "-"), f"多 {futures.get('longFormat', '-')}/空 {futures.get('shortFormat', '-')}", futures.get("net")),
        ("前五大交易人", large.get("top5NetFormat", "-"), f"{'多方主導' if large.get('top5Bias') == 'long' else '空方主導' if large.get('top5Bias') == 'short' else '中性'}", large.get("top5Net")),
        ("前十大交易人", large.get("top10NetFormat", "-"), f"{'多方主導' if large.get('top10Bias') == 'long' else '空方主導' if large.get('top10Bias') == 'short' else '中性'}", large.get("top10Net")),
        ("選擇權 PCR", pcr.get("openInterestPcrFormat", "-"), f"成交量 {pcr.get('volumePcrFormat', '-')}", pcr.get("openInterestPcr", 0) - 100),
        ("小台散戶多空比", retail.get("retailLongShortRatioFormat", "-"), f"留倉 {retail.get('retailPositionFormat', '-')}", retail.get("retailLongShortRatio")),
    ]
    x0, y0, card_w, card_h, gap = 50, 132, 348, 112, 20
    for index, (label, value, sub, tone_value) in enumerate(cards):
        x = x0 + (index % 3) * (card_w + gap)
        y = y0 + (index // 3) * (card_h + gap)
        draw.rounded_rectangle((x, y, x + card_w, y + card_h), radius=8, fill="#f9fafb", outline="#e5e7eb")
        draw.text((x + 16, y + 14), label, fill="#667085", font=small_font)
        draw.text((x + 16, y + 40), str(value), fill=color(tone_value), font=metric_font)
        draw.text((x + 16, y + 82), str(sub)[:28], fill="#667085", font=small_font)

    def draw_bar_panel(bounds: tuple[int, int, int, int], title_text: str, data_path: str) -> None:
        left, top, right, bottom = bounds
        draw.text((left, top - 24), title_text, fill="#667085", font=small_font)
        values = [nested_number(row, data_path) for row in reversed(rows[:LOOKBACK_ROWS])]
        if not values:
            return
        max_abs = max(abs(value) for value in values) or 1
        mid = (top + bottom) // 2
        draw.line((left, mid, right, mid), fill="#d9dee8", width=1)
        bar_gap = 2
        bar_w = max(3, int((right - left) / max(len(values), 1)) - bar_gap)
        for i, value in enumerate(values):
            x = left + i * (right - left) / max(len(values), 1)
            bar_h = abs(value) / max_abs * ((bottom - top) / 2 - 4)
            y0, y1 = (mid - bar_h, mid) if value >= 0 else (mid, mid + bar_h)
            draw.rectangle((x, y0, x + bar_w, y1), fill=color(value))

    draw_bar_panel((60, 542, 570, 638), "外資選擇權金額近 30 日", "foreignOptionAmount.netAmount")
    draw_bar_panel((630, 542, 1140, 638), "外資選擇權淨額近 30 日", "txoInstitutionalOpenInterest.foreign.netLot")
    img.save(path)


def draw_history_detail_chart(payload: dict[str, Any], path: Path, limit: int = 15) -> None:
    if Image is None or ImageDraw is None:
        return
    rows = (payload.get("rows") or [])[:limit]
    width = 1900
    row_h = 42
    top_margin = 92
    height = top_margin + 48 + max(len(rows), 1) * row_h + 36
    img = Image.new("RGB", (width, height), "#f6f8fb")
    draw = ImageDraw.Draw(img)
    try:
        title_font = ImageFont.truetype("msjh.ttc", 34)
        header_font = ImageFont.truetype("msjh.ttc", 18)
        cell_font = ImageFont.truetype("msjh.ttc", 18)
        small_font = ImageFont.truetype("msjh.ttc", 15)
    except Exception:
        title_font = header_font = cell_font = small_font = ImageFont.load_default()

    def color(value: Any) -> str:
        number = safe_number(value)
        if number > 0:
            return "#111827"
        if number < 0:
            return "#d92d20"
        return "#8a94a6"

    def text_fit(text: Any, limit_chars: int) -> str:
        value = str(text if text not in {None, ""} else "-")
        return value if len(value) <= limit_chars else value[: max(limit_chars - 1, 1)] + "…"

    columns = [
        ("日期", 105, lambda r: (r.get("dateLabel", "-")[5:], None)),
        ("判讀", 130, lambda r: (compact_view_label((r.get("foreignPositionView") or {}).get("label", "-")), (r.get("foreignPositionView") or {}).get("score"))),
        ("大盤", 145, lambda r: ((r.get("marketIndex") or {}).get("taiexCloseFormat", "-"), None)),
        ("漲跌%", 95, lambda r: ((r.get("marketIndex") or {}).get("taiexChangePercentFormat", "-"), (r.get("marketIndex") or {}).get("taiexChangePercent"))),
        ("外資", 130, lambda r: ((r.get("spotInstitutional") or {}).get("foreignNetBuyAmountYiFormat", "-").replace("億", ""), (r.get("spotInstitutional") or {}).get("foreignNetBuyAmount"))),
        ("外資期貨", 120, lambda r: (((r.get("futuresInstitutional") or {}).get("foreign") or {}).get("netFormat", "-"), ((r.get("futuresInstitutional") or {}).get("foreign") or {}).get("net"))),
        ("前五大", 115, lambda r: ((r.get("largeTraderFutures") or {}).get("top5NetFormat", "-"), (r.get("largeTraderFutures") or {}).get("top5Net"))),
        ("前十大", 115, lambda r: ((r.get("largeTraderFutures") or {}).get("top10NetFormat", "-"), (r.get("largeTraderFutures") or {}).get("top10Net"))),
        ("PCR", 105, lambda r: ((r.get("optionPcr") or {}).get("openInterestPcrFormat", "-"), None)),
        ("小台散戶", 130, lambda r: ((r.get("retailMiniFutures") or {}).get("retailLongShortRatioFormat", "-"), (r.get("retailMiniFutures") or {}).get("retailLongShortRatio"))),
        ("外選金", 125, lambda r: ((r.get("foreignOptionAmount") or {}).get("netAmountFormat", "-"), (r.get("foreignOptionAmount") or {}).get("netAmount"))),
        ("外選淨", 115, lambda r: ((((r.get("txoInstitutionalOpenInterest") or {}).get("foreign") or {}).get("netLotFormat", "-")), (((r.get("txoInstitutionalOpenInterest") or {}).get("foreign") or {}).get("netLot")))),
        ("自營選金", 125, lambda r: ((((r.get("optionInstitutionalAmount") or {}).get("dealer") or {}).get("netAmountFormat", "-")), (((r.get("optionInstitutionalAmount") or {}).get("dealer") or {}).get("netAmount")))),
        ("自營選淨", 115, lambda r: ((((r.get("txoInstitutionalOpenInterest") or {}).get("dealer") or {}).get("netLotFormat", "-")), (((r.get("txoInstitutionalOpenInterest") or {}).get("dealer") or {}).get("netLot")))),
    ]
    total_table_w = sum(width for _, width, _ in columns)
    left = (width - total_table_w) // 2
    right = left + total_table_w

    latest = payload.get("latest") or {}
    draw.rounded_rectangle((24, 20, width - 24, height - 20), radius=12, fill="#ffffff", outline="#d7dee9")
    draw.text((left, 38), "近 15 日籌碼明細", fill="#111827", font=title_font)
    draw.text((left, 76), f"最新日期 {latest.get('dateLabel', '-')}｜正值黑色，負值紅色", fill="#667085", font=small_font)

    y = top_margin
    draw.rectangle((left, y, right, y + 38), fill="#f9fafb", outline="#d9dee8")
    x = left
    for header, col_w, _ in columns:
        draw.text((x + 8, y + 9), header, fill="#667085", font=header_font)
        x += col_w
        draw.line((x, y, x, y + 38 + max(len(rows), 1) * row_h), fill="#edf0f5", width=1)

    for row_index, row in enumerate(rows):
        y = top_margin + 38 + row_index * row_h
        fill = "#ffffff" if row_index % 2 == 0 else "#fcfcfd"
        draw.rectangle((left, y, right, y + row_h), fill=fill, outline="#edf0f5")
        x = left
        for _, col_w, getter in columns:
            value, tone = getter(row)
            fill_color = color(tone) if tone is not None else "#111827"
            draw.text((x + 8, y + 10), text_fit(value, max(4, col_w // 14)), fill=fill_color, font=cell_font)
            x += col_w

    if not rows:
        draw.text((left + 20, top_margin + 62), "尚無資料", fill="#667085", font=cell_font)
    img.save(path)


def draw_history_detail_chart(payload: dict[str, Any], path: Path, limit: int = 15) -> None:
    if Image is None or ImageDraw is None:
        return
    rows = (payload.get("rows") or [])[:limit]
    width = 1900
    row_h = 48
    top_margin = 128
    height = top_margin + 54 + max(len(rows), 1) * row_h + 54
    img = Image.new("RGB", (width, height), "#f0f0f0")
    draw = ImageDraw.Draw(img)
    try:
        title_font = ImageFont.truetype("msjh.ttc", 42)
        header_font = ImageFont.truetype("msjh.ttc", 18)
        cell_font = ImageFont.truetype("msjh.ttc", 18)
        small_font = ImageFont.truetype("msjh.ttc", 16)
    except Exception:
        title_font = header_font = cell_font = small_font = ImageFont.load_default()

    def color(value: Any) -> str:
        number = safe_number(value)
        if number > 0:
            return "#1e325a"
        if number < 0:
            return "#d92d20"
        return "#7a8391"

    def text_fit(value: Any, limit_chars: int) -> str:
        content = str(value if value not in {None, ""} else "-")
        return content if len(content) <= limit_chars else content[: max(limit_chars - 1, 1)] + "…"

    columns = [
        ("日期", 105, lambda r: (r.get("dateLabel", "-")[5:], None)),
        ("判讀", 130, lambda r: (compact_view_label((r.get("foreignPositionView") or {}).get("label", "-")), (r.get("foreignPositionView") or {}).get("score"))),
        ("大盤", 145, lambda r: ((r.get("marketIndex") or {}).get("taiexCloseFormat", "-"), None)),
        ("漲跌%", 95, lambda r: ((r.get("marketIndex") or {}).get("taiexChangePercentFormat", "-"), (r.get("marketIndex") or {}).get("taiexChangePercent"))),
        ("外資買賣超", 130, lambda r: ((r.get("spotInstitutional") or {}).get("foreignNetBuyAmountYiFormat", "-").replace("億", ""), (r.get("spotInstitutional") or {}).get("foreignNetBuyAmount"))),
        ("外資期貨", 120, lambda r: (((r.get("futuresInstitutional") or {}).get("foreign") or {}).get("netFormat", "-"), ((r.get("futuresInstitutional") or {}).get("foreign") or {}).get("net"))),
        ("前五大", 115, lambda r: ((r.get("largeTraderFutures") or {}).get("top5NetFormat", "-"), (r.get("largeTraderFutures") or {}).get("top5Net"))),
        ("前十大", 115, lambda r: ((r.get("largeTraderFutures") or {}).get("top10NetFormat", "-"), (r.get("largeTraderFutures") or {}).get("top10Net"))),
        ("PCR", 105, lambda r: ((r.get("optionPcr") or {}).get("openInterestPcrFormat", "-"), None)),
        ("小台散戶", 130, lambda r: ((r.get("retailMiniFutures") or {}).get("retailLongShortRatioFormat", "-"), (r.get("retailMiniFutures") or {}).get("retailLongShortRatio"))),
        ("外資選擇權", 125, lambda r: ((r.get("foreignOptionAmount") or {}).get("netAmountFormat", "-"), (r.get("foreignOptionAmount") or {}).get("netAmount"))),
        ("外資選淨額", 115, lambda r: ((((r.get("txoInstitutionalOpenInterest") or {}).get("foreign") or {}).get("netLotFormat", "-")), (((r.get("txoInstitutionalOpenInterest") or {}).get("foreign") or {}).get("netLot")))),
        ("自營選擇權", 125, lambda r: ((((r.get("optionInstitutionalAmount") or {}).get("dealer") or {}).get("netAmountFormat", "-")), (((r.get("optionInstitutionalAmount") or {}).get("dealer") or {}).get("netAmount")))),
        ("自營選淨額", 115, lambda r: ((((r.get("txoInstitutionalOpenInterest") or {}).get("dealer") or {}).get("netLotFormat", "-")), (((r.get("txoInstitutionalOpenInterest") or {}).get("dealer") or {}).get("netLot")))),
    ]
    table_width = sum(col_width for _, col_width, _ in columns)
    left = (width - table_width) // 2
    right = left + table_width
    latest = payload.get("latest") or {}

    draw.rounded_rectangle((28, 24, width - 28, height - 24), radius=46, fill="#f8f8f8", outline="#ffffff", width=2)
    draw.rounded_rectangle((left, 42, left + 245, 80), radius=19, fill="#ffffff", outline="#dfe3ea")
    draw.text((left + 18, 51), "TWSE / TAIFEX", fill="#1e325a", font=small_font)
    draw.text((left, 88), "近 15 日市場明細", fill="#1e325a", font=title_font)
    draw.text((left + 430, 102), f"最新資料 {latest.get('dateLabel', '-')} / 偏多深藍，偏空紅色，中性灰色", fill="#5e6470", font=small_font)

    y = top_margin
    draw.rounded_rectangle((left, y, right, y + 42), radius=18, fill="#ffffff", outline="#dfe3ea")
    x = left
    for header, col_width, _ in columns:
        draw.text((x + 10, y + 11), header, fill="#5e6470", font=header_font)
        x += col_width
        draw.line((x, y + 7, x, y + 42 + max(len(rows), 1) * row_h), fill="#e8ebf0", width=1)

    for row_index, row in enumerate(rows):
        y = top_margin + 42 + row_index * row_h
        fill = "#ffffff" if row_index % 2 == 0 else "#f6f7f9"
        draw.rounded_rectangle((left, y + 4, right, y + row_h - 4), radius=14, fill=fill, outline="#edf0f5")
        x = left
        for _, col_width, getter in columns:
            value, tone = getter(row)
            fill_color = color(tone) if tone is not None else "#111827"
            draw.text((x + 10, y + 14), text_fit(value, max(4, col_width // 14)), fill=fill_color, font=cell_font)
            x += col_width

    if not rows:
        draw.text((left + 20, top_margin + 68), "尚無資料", fill="#5e6470", font=cell_font)
    img.save(path)


def generate_static_files(payload: dict[str, Any]) -> None:
    ensure_dirs()
    draw_snapshot_chart(payload, STATIC_DIR / "overview-chart.png")
    draw_snapshot_chart(payload, STATIC_DIR / "latest-chart.png")
    draw_history_detail_chart(payload, STATIC_DIR / "discord-history-detail.png")


def ensure_overview_chart(payload: dict[str, Any]) -> Path:
    chart_path = STATIC_DIR / "overview-chart.png"
    if not chart_path.exists():
        draw_snapshot_chart(payload, chart_path)
    return chart_path


def ensure_discord_history_chart(payload: dict[str, Any]) -> Path:
    chart_path = STATIC_DIR / "discord-history-detail.png"
    draw_history_detail_chart(payload, chart_path)
    return chart_path


def build_discord_message(payload: dict[str, Any], category: str = "overview") -> dict[str, Any]:
    content = discord_summary(payload, category)
    chart_path = ensure_discord_history_chart(payload)
    latest = payload.get("latest") or {}
    return {
        "content": content,
        "chartPath": chart_path,
        "dateLabel": latest.get("dateLabel"),
        "fetchedAt": payload.get("fetchedAt"),
    }


def compact_view_label(value: str) -> str:
    text = value or "-"
    return text.replace("外資", "").replace(" / 訊號不足", "").replace("偏對沖", "對沖")


def discord_summary(payload: dict[str, Any], category: str = "overview") -> str:
    latest = payload.get("latest") or {}
    if not latest:
        return "目前尚無每日籌碼資料，請先更新資料。"
    foreign_view = latest.get("foreignPositionView") or build_foreign_position_view(latest)
    option_views = latest.get("optionPositionViews") or build_option_position_views(latest)
    dealer_view = option_views.get("dealer") or {}
    explanation_lines = foreign_view.get("explanationLines") or []
    lines = [
        f"**{latest.get('dateLabel')} 外資操作判讀**",
        f"判讀結果：{foreign_view.get('label', '中性 / 訊號不足')}",
        f"多空強度：{foreign_view.get('confidence', '-')}",
        f"判讀理由：{foreign_view.get('reason', '-')}",
    ]
    if explanation_lines:
        lines.extend(str(line) for line in explanation_lines if not str(line).startswith("多空強度："))
    elif foreign_view.get("explanation"):
        lines.append(str(foreign_view.get("explanation")))
    lines.extend([
        "",
        "**自營商選擇權籌碼**",
        f"判讀結果：{dealer_view.get('label', '中性')}",
        f"判讀理由：{dealer_view.get('reason', '自營商選擇權缺資料')}",
    ])
    return "\n".join(lines)


async def send_discord_report(payload: dict[str, Any] | None = None, category: str = "overview") -> None:
    if payload is None:
        payload = store.load()
    if not DISCORD_CHANNEL_IDS:
        raise RuntimeError("DISCORD_CHANNEL_IDS is not configured.")
    if discord_client is None:
        raise RuntimeError("Discord bot is not running.")
    message = build_discord_message(payload, category)
    chart_path = message["chartPath"]
    discord = require_discord()
    for channel_id in DISCORD_CHANNEL_IDS:
        channel = discord_client.get_channel(channel_id) or await discord_client.fetch_channel(channel_id)
        await channel.send(
            content=message["content"],
            file=discord.File(str(chart_path), filename=chart_path.name) if chart_path.exists() else None,
        )


def post_discord_rest_report(payload: dict[str, Any] | None = None, category: str = "overview") -> dict[str, Any]:
    if payload is None:
        payload = store.load()
    if not DISCORD_BOT_TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN is not configured.")
    if not DISCORD_CHANNEL_IDS:
        raise RuntimeError("DISCORD_CHANNEL_IDS is not configured.")
    message = build_discord_message(payload, category)
    chart_path = message["chartPath"]
    boundary = f"----chip-dashboard-{uuid.uuid4().hex}"
    body = bytearray()

    def add_part(name: str, data: bytes, content_type: str, filename: str | None = None) -> None:
        body.extend(f"--{boundary}\r\n".encode())
        disposition = f'form-data; name="{name}"'
        if filename:
            disposition += f'; filename="{filename}"'
        body.extend(f"Content-Disposition: {disposition}\r\n".encode())
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode())
        body.extend(data)
        body.extend(b"\r\n")

    add_part("payload_json", json.dumps({"content": message["content"]}, ensure_ascii=False).encode("utf-8"), "application/json")
    if chart_path.exists():
        add_part("files[0]", chart_path.read_bytes(), "image/png", chart_path.name)
    body.extend(f"--{boundary}--\r\n".encode())
    results = []
    for channel_id in DISCORD_CHANNEL_IDS:
        req = urllib.request.Request(
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            data=bytes(body),
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            text = response.read().decode("utf-8", errors="replace")
            results.append({"channelId": channel_id, "status": response.status, "body": json.loads(text) if text else {}})
    return {
        "status": results[-1]["status"] if results else 0,
        "results": results,
        "dateLabel": message["dateLabel"],
        "fetchedAt": message["fetchedAt"],
        "channelCount": len(DISCORD_CHANNEL_IDS),
        "contentLength": len(message["content"]),
    }


def scheduler_loop() -> None:
    global last_scheduler_run, last_error
    scheduled_at = parse_schedule_time(SCHEDULE_TIME)
    current = now_taipei()
    if current.time() >= scheduled_at:
        last_scheduler_run = current.strftime("%Y-%m-%d")
    while True:
        try:
            current = now_taipei()
            today_key = current.strftime("%Y-%m-%d")
            if should_run_daily_schedule(current, scheduled_at, last_scheduler_run):
                payload = refresh_data()
                last_scheduler_run = today_key
                if DISCORD_SEND_AFTER_REFRESH and discord_configured() and discord_client:
                    asyncio.run_coroutine_threadsafe(send_discord_report(payload), discord_client.loop)
                elif DISCORD_SEND_AFTER_REFRESH and discord_configured():
                    post_discord_rest_report(payload)
        except Exception:
            last_error = traceback.format_exc()
            print(last_error)
        time.sleep(60)


class AppHandler(BaseHTTPRequestHandler):
    server_version = "ChipDashboard/2.0"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, content_type: str | None = None) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Last-Modified", email.utils.formatdate(path.stat().st_mtime, usegmt=True))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self.send_html(load_index_html())
        elif parsed.path == "/api/data":
            self.send_json({
                **store.load(),
                "scheduler": {
                    "timezone": TIMEZONE_NAME,
                    "time": SCHEDULE_TIME,
                    "weekdaysOnly": True,
                    "lastRun": last_scheduler_run,
                    "lastError": last_error,
                    "discordBotConfigured": discord_configured(),
                    "discordChannelCount": len(DISCORD_CHANNEL_IDS),
                    "discordBotEnabled": DISCORD_BOT_ENABLED,
                },
            })
        elif parsed.path == "/chart.png":
            payload = store.load()
            chart_path = ensure_overview_chart(payload)
            self.send_file(chart_path, "image/png")
        elif parsed.path.startswith("/static/"):
            requested = (STATIC_DIR / parsed.path.removeprefix("/static/")).resolve()
            if STATIC_DIR.resolve() not in requested.parents and requested != STATIC_DIR.resolve():
                self.send_error(HTTPStatus.FORBIDDEN.value)
                return
            self.send_file(requested)
        elif parsed.path.startswith("/assets/"):
            requested = (FRONTEND_DIST_DIR / parsed.path.removeprefix("/")).resolve()
            if FRONTEND_DIST_DIR.resolve() not in requested.parents and requested != FRONTEND_DIST_DIR.resolve():
                self.send_error(HTTPStatus.FORBIDDEN.value)
                return
            self.send_file(requested)
        else:
            self.send_error(HTTPStatus.NOT_FOUND.value)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/refresh":
                payload = refresh_data()
                self.send_json({"ok": True, "latest": payload.get("latest"), "fetchedAt": payload.get("fetchedAt"), "lastError": payload.get("lastError")})
            elif parsed.path == "/api/send-discord":
                query = urllib.parse.parse_qs(parsed.query)
                category = query.get("category", ["overview"])[0]
                payload = store.load()
                if not payload.get("latest"):
                    payload = refresh_data()
                message = build_discord_message(payload, category)
                if discord_client:
                    asyncio.run_coroutine_threadsafe(send_discord_report(payload, category), discord_client.loop)
                    self.send_json({
                        "ok": True,
                        "mode": "bot",
                        "dateLabel": message["dateLabel"],
                        "fetchedAt": message["fetchedAt"],
                        "channelCount": len(DISCORD_CHANNEL_IDS),
                        "contentLength": len(message["content"]),
                    })
                else:
                    result = post_discord_rest_report(payload, category)
                    self.send_json({
                        "ok": True,
                        "mode": "rest",
                        "dateLabel": result.get("dateLabel"),
                        "fetchedAt": result.get("fetchedAt"),
                        "channelCount": result.get("channelCount"),
                        "contentLength": result.get("contentLength"),
                        "discord": {"status": result["status"]},
                    })
            else:
                self.send_error(HTTPStatus.NOT_FOUND.value)
        except Exception as exc:
            global last_error
            last_error = traceback.format_exc()
            self.send_json({"ok": False, "error": str(exc), "trace": last_error}, HTTPStatus.INTERNAL_SERVER_ERROR)


def discord_configured() -> bool:
    return bool(DISCORD_BOT_TOKEN and DISCORD_CHANNEL_IDS)


def require_discord() -> Any:
    try:
        import discord
        from discord import app_commands
    except Exception as exc:
        raise RuntimeError("discord.py is required for bot mode. Install dependencies with: pip install -r requirements.txt") from exc
    return discord


class CategorySwitchView:
    def __new__(cls, payload: dict[str, Any]) -> Any:
        discord = require_discord()

        class _View(discord.ui.View):
            def __init__(self, data: dict[str, Any]) -> None:
                super().__init__(timeout=300)
                self.data = data

            async def _send(self, interaction: Any, category: str) -> None:
                await interaction.response.send_message(discord_summary(self.data, category), ephemeral=True)

            @discord.ui.button(label="總覽", style=discord.ButtonStyle.primary)
            async def overview_button(self, interaction: Any, button: Any) -> None:
                await self._send(interaction, "overview")

            @discord.ui.button(label="現貨", style=discord.ButtonStyle.secondary)
            async def cash_button(self, interaction: Any, button: Any) -> None:
                await self._send(interaction, "cash")

            @discord.ui.button(label="期貨", style=discord.ButtonStyle.secondary)
            async def futures_button(self, interaction: Any, button: Any) -> None:
                await self._send(interaction, "futures")

            @discord.ui.button(label="選擇權", style=discord.ButtonStyle.secondary)
            async def options_button(self, interaction: Any, button: Any) -> None:
                await self._send(interaction, "options")

        return _View(payload)


def create_discord_bot() -> Any:
    discord = require_discord()
    from discord import app_commands
    intents = discord.Intents.default()
    bot = discord.Client(intents=intents)
    tree = app_commands.CommandTree(bot)

    @bot.event
    async def on_ready() -> None:
        await tree.sync()
        print(f"Discord bot logged in as {bot.user}")

    @tree.command(name="stock_today", description="傳送每日籌碼總覽")
    async def stock_today(interaction: Any) -> None:
        payload = store.load()
        message = build_discord_message(payload)
        chart_path = message["chartPath"]
        await interaction.response.send_message(
            content=message["content"],
            file=discord.File(str(chart_path), filename=chart_path.name) if chart_path.exists() else None,
        )

    @tree.command(name="stock_chart", description="傳送每日籌碼快照圖")
    async def stock_chart(interaction: Any) -> None:
        payload = store.load()
        message = build_discord_message(payload)
        chart_path = message["chartPath"]
        await interaction.response.send_message(
            content=message["content"],
            file=discord.File(str(chart_path), filename=chart_path.name) if chart_path.exists() else None,
        )

    @tree.command(name="stock_refresh", description="更新每日籌碼資料")
    async def stock_refresh(interaction: Any) -> None:
        await interaction.response.defer(thinking=True)
        try:
            payload = await asyncio.to_thread(refresh_data)
            message = build_discord_message(payload)
            chart_path = message["chartPath"]
            await interaction.followup.send(
                content=message["content"],
                file=discord.File(str(chart_path), filename=chart_path.name) if chart_path.exists() else None,
            )
        except Exception as exc:
            await interaction.followup.send(f"更新失敗：{exc}")

    return bot


def load_index_html() -> str:
    if FRONTEND_INDEX_PATH.exists():
        return FRONTEND_INDEX_PATH.read_text(encoding="utf-8")
    return """<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Neuralyn frontend not built</title>
  <style>
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #000; color: #fff; font-family: system-ui, sans-serif; }
    main { width: min(680px, calc(100% - 40px)); border: 1px solid #333; border-radius: 16px; padding: 28px; background: #0d0d0d; }
    code { color: #d4d4d4; }
    p { color: #a3a3a3; line-height: 1.7; }
  </style>
</head>
<body>
  <main>
    <h1>Neuralyn frontend 尚未建置</h1>
    <p>請先進入 <code>frontend</code> 執行 <code>npm install</code> 與 <code>npm run build</code>，再重新整理此頁。</p>
  </main>
</body>
</html>"""


def run_web_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((DEFAULT_HOST, DEFAULT_PORT), AppHandler)
    print(f"Serving {APP_BASE_URL}")
    print(f"Daily refresh: weekdays at {SCHEDULE_TIME} {TIMEZONE_NAME}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> None:
    ensure_dirs()
    if RUN_ON_STARTUP:
        try:
            refresh_data()
        except Exception:
            global last_error
            last_error = traceback.format_exc()
            print(last_error)
            generate_static_files(store.load())
    else:
        generate_static_files(store.load())

    run_web_server()
    threading.Thread(target=scheduler_loop, daemon=True).start()

    global discord_client
    if DISCORD_BOT_ENABLED and DISCORD_BOT_TOKEN:
        try:
            discord_client = create_discord_bot()
            discord_client.run(DISCORD_BOT_TOKEN)
        except Exception:
            print("Discord bot failed to start. Web server will keep running.")
            print(traceback.format_exc())
            while True:
                time.sleep(3600)
    else:
        if not DISCORD_BOT_ENABLED:
            print("Discord bot disabled: DISCORD_BOT_ENABLED=0.")
        elif not DISCORD_BOT_TOKEN:
            print("Discord bot disabled: DISCORD_BOT_TOKEN is not configured.")
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
