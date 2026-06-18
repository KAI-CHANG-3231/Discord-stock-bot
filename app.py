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
import uuid
import urllib.error
import urllib.parse
import urllib.request
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
except Exception:  # pragma: no cover - the web app still works without PNG export
    Image = None
    ImageDraw = None
    ImageFont = None


BASE_DIR = Path(__file__).resolve().parent


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_json_env(path: Path) -> None:
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, (list, dict)):
            text = json.dumps(value, ensure_ascii=False)
        else:
            text = str(value).strip()
        if text:
            os.environ[str(key)] = text


load_dotenv(BASE_DIR / ".env")
load_json_env(BASE_DIR / "discord_config.json")

DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"

TAIFEX_CALLS_PUTS_URL = "https://www.taifex.com.tw/cht/3/callsAndPutsDate"
TAIFEX_FUT_CONTRACTS_URL = "https://www.taifex.com.tw/cht/3/futContractsDate"
TAIFEX_FUT_DAILY_URL = "https://www.taifex.com.tw/cht/3/futDailyMarketReport"
TWSE_TAIEX_URL = "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST"
TAIFEX_SOURCE_LABEL = "臺灣期貨交易所 選擇權買賣權分計-依日期"
PRODUCT_ID = "TXO"
PRODUCT_NAME = "臺指選擇權"
MINI_FUTURES_CONTRACTS_ID = "MXF"
MINI_FUTURES_MARKET_ID = "MTX"
MINI_FUTURES_NAME = "小型臺指期貨"
RETAIL_SOURCE_LABEL = "臺灣期貨交易所 小台指散戶多空比推導"
MARKET_INDEX_SOURCE_LABEL = "臺灣證券交易所 TAIEX 加權指數"

DEFAULT_HOST = os.getenv("HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("PORT", "8080"))
APP_BASE_URL = os.getenv("APP_BASE_URL", f"http://{DEFAULT_HOST}:{DEFAULT_PORT}")
TIMEZONE_NAME = os.getenv("TIMEZONE", "Asia/Taipei")
SCHEDULE_TIME = os.getenv("SCHEDULE_TIME", "16:20")
LOOKBACK_ROWS = int(os.getenv("LOOKBACK_ROWS", "30"))
RETAIL_MAX_NEW_DAYS = int(os.getenv("RETAIL_MAX_NEW_DAYS", str(LOOKBACK_ROWS)))
RETAIL_REQUEST_DELAY = float(os.getenv("RETAIL_REQUEST_DELAY", "0.4"))
RUN_ON_STARTUP = os.getenv("RUN_ON_STARTUP", "1") == "1"

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
if DISCORD_BOT_TOKEN.lower().startswith("bot "):
    DISCORD_BOT_TOKEN = DISCORD_BOT_TOKEN[4:].strip()


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

    channel_ids: list[int] = []
    for value in values:
        text = str(value).strip().strip('"').strip("'")
        if not text or text == "0":
            continue
        try:
            channel_id = int(text)
        except ValueError:
            continue
        if channel_id not in channel_ids:
            channel_ids.append(channel_id)
    return channel_ids


DISCORD_CHANNEL_IDS = parse_discord_channel_ids()
DISCORD_SEND_AFTER_REFRESH = os.getenv("DISCORD_SEND_AFTER_REFRESH", "1") == "1"
DISCORD_BOT_ENABLED = os.getenv("DISCORD_BOT_ENABLED", "1") == "1"
DISCORD_API_BASE = "https://discord.com/api/v10"


def discord_configured() -> bool:
    return bool(DISCORD_BOT_TOKEN and DISCORD_CHANNEL_IDS)

IDENTITY_LABELS = {
    "foreign": "外資",
    "investmentTrust": "投信",
    "dealer": "自營商",
}
IDENTITY_KEYS = {value: key for key, value in IDENTITY_LABELS.items()}
IDENTITY_ORDER = ["foreign", "investmentTrust", "dealer"]
IDENTITY_COLORS = {
    "foreign": ("#d64b5f", "#1f9d68", "#3368d8"),
    "investmentTrust": ("#b25dd8", "#198f9f", "#e08a2e"),
    "dealer": ("#e06d32", "#2674a6", "#5963d8"),
}


def now_taipei() -> datetime:
    try:
        tz = ZoneInfo(TIMEZONE_NAME)
    except ZoneInfoNotFoundError:
        tz = timezone(timedelta(hours=8), name="Asia/Taipei")
    return datetime.now(tz)


def parse_schedule_time(value: str) -> clock_time:
    hour, minute = value.split(":", 1)
    return clock_time(hour=int(hour), minute=int(minute))


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    STATIC_DIR.mkdir(exist_ok=True)


def safe_number(value: Any, default: float = 0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").strip()
    if not text or text == "-":
        return default
    try:
        return float(text)
    except ValueError:
        return default


def as_int(value: Any) -> int:
    return int(round(safe_number(value)))


def fmt_int(value: Any) -> str:
    return f"{as_int(value):,}"


def fmt_signed(value: Any) -> str:
    number = as_int(value)
    sign = "+" if number > 0 else ""
    return f"{sign}{number:,}"


def fmt_float(value: Any, digits: int = 2) -> str:
    return f"{safe_number(value):,.{digits}f}"


def fmt_signed_float(value: Any, digits: int = 2) -> str:
    number = safe_number(value)
    sign = "+" if number > 0 else ""
    return f"{sign}{number:,.{digits}f}"


def fmt_signed_percent(value: Any, digits: int = 2) -> str:
    return f"{fmt_signed_float(value, digits)}%"


def parse_taifex_date(value: str) -> date:
    return datetime.strptime(value, "%Y/%m/%d").date()


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


def public_row(row: dict[str, Any]) -> dict[str, Any]:
    hidden = {"raw"}
    return {key: value for key, value in row.items() if key not in hidden}


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
            text = " ".join(text.split())
            self._cells.append(text)
            self._in_cell = False
        elif self._in_row and tag == "tr":
            if self._cells:
                self.rows.append(self._cells)
            self._in_row = False


@dataclass
class OptionSide:
    oi_buy_lot: int = 0
    oi_buy_amount: int = 0
    oi_sell_lot: int = 0
    oi_sell_amount: int = 0


class TaifexClient:
    def __init__(self) -> None:
        self.opener = urllib.request.build_opener()

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": TAIFEX_CALLS_PUTS_URL,
        }

    def _request(self, query_date: date | None = None) -> str:
        data = None
        headers = self._headers()
        if query_date:
            form = {
                "queryDate": taifex_date(query_date),
                "commodityId": PRODUCT_ID,
                "queryType": "",
                "goDay": "",
                "doQuery": "1",
                "dateaddcnt": "",
            }
            data = urllib.parse.urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        req = urllib.request.Request(TAIFEX_CALLS_PUTS_URL, data=data, headers=headers)
        with self.opener.open(req, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")

    def latest_trade_date(self) -> date:
        text = self._request()
        return extract_display_date(text)

    def fetch_day(self, query_date: date) -> dict[str, Any] | None:
        text = self._request(query_date)
        try:
            displayed_date = extract_display_date(text)
        except ValueError:
            return None
        if displayed_date != query_date:
            return None
        return parse_calls_puts_page(text, displayed_date)

    def fetch_history(self, limit: int = LOOKBACK_ROWS) -> dict[str, Any]:
        latest = self.latest_trade_date()
        rows: list[dict[str, Any]] = []
        cursor = latest
        misses = 0
        max_calendar_days = max(limit * 3, 90)

        while len(rows) < limit and misses <= max_calendar_days:
            item = self.fetch_day(cursor)
            if item:
                rows.append(item)
            cursor -= timedelta(days=1)
            misses += 1

        rows.sort(key=lambda item: item["date"], reverse=True)
        attach_diffs(rows)
        return {
            "source": TAIFEX_SOURCE_LABEL,
            "sourceUrl": TAIFEX_CALLS_PUTS_URL,
            "productId": PRODUCT_ID,
            "productName": PRODUCT_NAME,
            "tradeDate": rows[0]["dateLabel"] if rows else None,
            "fetchedAt": now_taipei().isoformat(timespec="seconds"),
            "rows": [public_row(row) for row in rows],
            "latest": public_row(rows[0]) if rows else None,
        }


class MarketIndexClient:
    def __init__(self) -> None:
        self.opener = urllib.request.build_opener()
        self.unverified_opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl._create_unverified_context())
        )

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.twse.com.tw/zh/indices/taiex/mi-5min-hist.html",
        }

    def _month_start(self, value: date) -> date:
        return value.replace(day=1)

    def _previous_month(self, value: date) -> date:
        if value.month == 1:
            return date(value.year - 1, 12, 1)
        return date(value.year, value.month - 1, 1)

    def _request_month(self, marker: date) -> dict[str, Any]:
        query = urllib.parse.urlencode({"date": marker.strftime("%Y%m%d"), "response": "json"})
        url = f"{TWSE_TAIEX_URL}?{query}"
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with self.opener.open(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8-sig"))
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ssl.SSLError):
                with self.unverified_opener.open(req, timeout=30) as response:
                    return json.loads(response.read().decode("utf-8-sig"))
            raise

    def fetch_history(
        self,
        limit: int = LOOKBACK_ROWS,
        latest: date | None = None,
        cached: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        latest = latest or now_taipei().date()
        month = self._month_start(latest)
        rows_by_date: dict[str, dict[str, Any]] = {}
        last_error: str | None = None

        for _ in range(4):
            try:
                marker = latest if month.year == latest.year and month.month == latest.month else date(month.year, month.month, 28)
                payload = self._request_month(marker)
                if payload.get("stat") == "OK":
                    for cells in payload.get("data") or []:
                        if len(cells) < 5:
                            continue
                        trade_date = parse_twse_date(str(cells[0]))
                        if trade_date > latest:
                            continue
                        close = safe_number(cells[4])
                        rows_by_date[trade_date.isoformat()] = {
                            "date": trade_date.isoformat(),
                            "dateLabel": date_label(trade_date),
                            "close": round(close, 2),
                            "closeFormat": fmt_float(close),
                        }
            except Exception as exc:
                last_error = str(exc)
            month = self._previous_month(month)
            if len(rows_by_date) >= limit + 1:
                break

        rows = sorted(rows_by_date.values(), key=lambda item: item["date"], reverse=True)[:limit]
        if not rows and cached and cached.get("rows"):
            fallback = dict(cached)
            fallback["lastError"] = last_error or "TWSE market index data is unavailable."
            return fallback
        if not rows:
            raise ValueError(last_error or "No TWSE TAIEX rows were found.")

        attach_market_index_diffs(rows)
        return {
            "source": MARKET_INDEX_SOURCE_LABEL,
            "sourceUrl": TWSE_TAIEX_URL,
            "productId": "TAIEX",
            "productName": "加權指數",
            "rows": rows,
            "latest": rows[0],
            "tradeDate": rows[0]["dateLabel"],
            "fetchedAt": now_taipei().isoformat(timespec="seconds"),
            "lastError": last_error,
        }


class RetailIndicatorClient:
    def __init__(self) -> None:
        self.opener = urllib.request.build_opener()

    def _headers(self, referer: str) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": referer,
        }

    def _post(self, url: str, form: dict[str, str]) -> str:
        headers = self._headers(url)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urllib.parse.urlencode(form).encode("utf-8")
        for attempt in range(3):
            req = urllib.request.Request(url, data=data, headers=headers)
            try:
                with self.opener.open(req, timeout=30) as response:
                    return response.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 2:
                    time.sleep(max(RETAIL_REQUEST_DELAY, 1.5) * (attempt + 1))
                    continue
                raise
        raise RuntimeError("TAIFEX request failed.")

    def latest_trade_date(self) -> date:
        text = self._post(
            TAIFEX_FUT_CONTRACTS_URL,
            {
                "queryDate": taifex_date(now_taipei().date()),
                "commodityId": MINI_FUTURES_CONTRACTS_ID,
                "queryType": "",
                "goDay": "",
                "doQuery": "1",
                "dateaddcnt": "",
            },
        )
        try:
            return extract_display_date(text)
        except ValueError:
            return now_taipei().date()

    def fetch_day(self, query_date: date) -> dict[str, Any] | None:
        contract_text = self._post(
            TAIFEX_FUT_CONTRACTS_URL,
            {
                "queryDate": taifex_date(query_date),
                "commodityId": MINI_FUTURES_CONTRACTS_ID,
                "queryType": "",
                "goDay": "",
                "doQuery": "1",
                "dateaddcnt": "",
            },
        )
        try:
            displayed_date = extract_display_date(contract_text)
        except ValueError:
            return None
        if displayed_date != query_date:
            return None

        daily_text = self._post(
            TAIFEX_FUT_DAILY_URL,
            {
                "queryDate": taifex_date(query_date),
                "MarketCode": "0",
                "commodity_id": MINI_FUTURES_MARKET_ID,
            },
        )
        institutional = parse_mini_futures_institutional_page(contract_text)
        market = parse_mini_futures_daily_page(daily_text)
        total_open_interest = market["openInterest"]
        if total_open_interest <= 0:
            return None

        retail_net = -institutional["institutionalNet"]
        retail_long = total_open_interest - institutional["institutionalLong"]
        retail_short = total_open_interest - institutional["institutionalShort"]
        ratio = round(retail_net / total_open_interest * 100, 2)

        row = {
            "date": query_date.isoformat(),
            "dateLabel": date_label(query_date),
            "close": market["close"],
            "settlement": market["settlement"],
            "totalOpenInterest": total_open_interest,
            "institutionalLong": institutional["institutionalLong"],
            "institutionalShort": institutional["institutionalShort"],
            "institutionalNet": institutional["institutionalNet"],
            "retailLong": retail_long,
            "retailShort": retail_short,
            "retailNet": retail_net,
            "retailLongShortRatio": ratio,
            "retailLongFormat": fmt_int(retail_long),
            "retailShortFormat": fmt_int(retail_short),
            "retailNetFormat": fmt_signed(retail_net),
            "totalOpenInterestFormat": fmt_int(total_open_interest),
            "retailLongShortRatioFormat": f"{ratio:.2f}%",
            "bias": retail_bias_label(ratio),
            "formula": "-1 * 小台指三大法人未平倉淨額 / 小台全體未平倉量",
        }
        return row

    def fetch_history(
        self,
        limit: int = LOOKBACK_ROWS,
        latest: date | None = None,
        cached: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        latest = latest or self.latest_trade_date()
        rows_by_date: dict[str, dict[str, Any]] = {}
        if cached and cached.get("source") == RETAIL_SOURCE_LABEL:
            for row in cached.get("rows") or []:
                if row.get("date") and row.get("totalOpenInterest"):
                    rows_by_date[row["date"]] = row

        rows: list[dict[str, Any]] = []
        cursor = latest
        misses = 0
        max_calendar_days = max(limit * 3, 90)
        new_fetches = 0
        last_fetch_error: str | None = None

        while len(rows) < limit and misses <= max_calendar_days:
            if cursor.weekday() >= 5:
                cursor -= timedelta(days=1)
                misses += 1
                continue
            key = cursor.isoformat()
            item = rows_by_date.get(key)
            if item is None and new_fetches < RETAIL_MAX_NEW_DAYS:
                try:
                    item = self.fetch_day(cursor)
                    new_fetches += 1
                    if RETAIL_REQUEST_DELAY > 0:
                        time.sleep(RETAIL_REQUEST_DELAY)
                except Exception as exc:
                    last_fetch_error = str(exc)
                    item = None
                    break
            if item:
                rows.append(item)
            cursor -= timedelta(days=1)
            misses += 1

        if not rows:
            if last_fetch_error:
                raise RuntimeError(last_fetch_error)
            raise ValueError("No official TAIFEX mini futures retail indicator rows were found.")
        rows.sort(key=lambda item: item["date"], reverse=True)
        attach_retail_diffs(rows)
        return {
            "source": RETAIL_SOURCE_LABEL,
            "sourceUrl": TAIFEX_FUT_CONTRACTS_URL,
            "marketSourceUrl": TAIFEX_FUT_DAILY_URL,
            "productId": MINI_FUTURES_MARKET_ID,
            "productName": MINI_FUTURES_NAME,
            "rows": rows,
            "latest": rows[0] if rows else None,
            "fetchedAt": now_taipei().isoformat(timespec="seconds"),
            "lastError": last_fetch_error,
        }


def parse_mini_futures_institutional_page(text: str) -> dict[str, int]:
    parser = TableParser()
    parser.feed(text)
    values = {"institutionalLong": 0, "institutionalShort": 0, "institutionalNet": 0}

    for cells in parser.rows:
        if not cells:
            continue
        if len(cells) >= 15 and cells[0].isdigit() and cells[1] == MINI_FUTURES_NAME:
            values["institutionalLong"] += as_int(cells[9])
            values["institutionalShort"] += as_int(cells[11])
            values["institutionalNet"] += as_int(cells[13])
        elif len(cells) >= 13 and cells[0] in IDENTITY_KEYS:
            values["institutionalLong"] += as_int(cells[7])
            values["institutionalShort"] += as_int(cells[9])
            values["institutionalNet"] += as_int(cells[11])

    if not values["institutionalLong"] and not values["institutionalShort"]:
        raise ValueError(f"No {MINI_FUTURES_NAME} institutional open interest rows were found.")
    return values


def parse_mini_futures_daily_page(text: str) -> dict[str, int]:
    parser = TableParser()
    parser.feed(text)
    front_close = 0
    front_settlement = 0
    total_open_interest = 0

    for cells in parser.rows:
        if len(cells) < 13 or cells[0] != MINI_FUTURES_MARKET_ID:
            continue
        expiry = cells[1]
        if "/" in expiry:
            continue
        if not front_close:
            front_close = as_int(cells[5])
            front_settlement = as_int(cells[11])
        total_open_interest += as_int(cells[12])

    if total_open_interest <= 0:
        raise ValueError(f"No {MINI_FUTURES_MARKET_ID} daily market open interest rows were found.")
    return {
        "close": front_close,
        "settlement": front_settlement,
        "openInterest": total_open_interest,
    }


def extract_display_date(text: str) -> date:
    match = re.search(r"日期\s*(\d{4}/\d{2}/\d{2})", text)
    if not match:
        raise ValueError("TAIFEX page did not include a data date.")
    return parse_taifex_date(match.group(1))


def attach_retail_diffs(rows: list[dict[str, Any]]) -> None:
    for index, row in enumerate(rows):
        previous = rows[index + 1] if index + 1 < len(rows) else None
        ratio_diff = safe_number(row.get("retailLongShortRatio")) - safe_number(previous.get("retailLongShortRatio")) if previous else 0
        long_diff = as_int(row.get("retailLong")) - as_int(previous.get("retailLong")) if previous else 0
        short_diff = as_int(row.get("retailShort")) - as_int(previous.get("retailShort")) if previous else 0
        row["retailLongShortRatioDiff"] = round(ratio_diff, 2)
        row["retailLongShortRatioDiffFormat"] = f"{ratio_diff:+.2f}%"
        row["retailLongDiff"] = long_diff
        row["retailShortDiff"] = short_diff
        row["retailLongDiffFormat"] = fmt_signed(long_diff)
        row["retailShortDiffFormat"] = fmt_signed(short_diff)


def attach_market_index_diffs(rows: list[dict[str, Any]]) -> None:
    for index, row in enumerate(rows):
        previous = rows[index + 1] if index + 1 < len(rows) else None
        close = safe_number(row.get("close"))
        previous_close = safe_number(previous.get("close")) if previous else 0
        change = close - previous_close if previous else 0
        change_percent = (change / previous_close * 100) if previous_close else 0
        row["previousClose"] = round(previous_close, 2) if previous else None
        row["previousCloseFormat"] = fmt_float(previous_close) if previous else "-"
        row["change"] = round(change, 2)
        row["changeFormat"] = fmt_signed_float(change)
        row["changePercent"] = round(change_percent, 2)
        row["changePercentFormat"] = fmt_signed_percent(change_percent)


def retail_bias_label(ratio: Any) -> str:
    value = safe_number(ratio)
    if value >= 15:
        return "偏多"
    if value <= -15:
        return "偏空"
    return "中性"


def parse_calls_puts_page(text: str, trade_date: date) -> dict[str, Any]:
    parser = TableParser()
    parser.feed(text)

    current_product = ""
    current_option = ""
    raw: dict[str, dict[str, OptionSide]] = {
        identity: {"買權": OptionSide(), "賣權": OptionSide()} for identity in IDENTITY_ORDER
    }

    for cells in parser.rows:
        if not cells:
            continue
        if cells[0].isdigit() and len(cells) >= 16:
            current_product = cells[1]
            current_option = cells[2]
            identity_label = cells[3]
            numbers = cells[4:]
        elif cells[0] in {"買權", "賣權"} and len(cells) >= 14:
            current_option = cells[0]
            identity_label = cells[1]
            numbers = cells[2:]
        elif cells[0] in IDENTITY_KEYS and len(cells) >= 13:
            identity_label = cells[0]
            numbers = cells[1:]
        else:
            continue

        if current_product != PRODUCT_NAME or current_option not in {"買權", "賣權"}:
            continue
        identity = IDENTITY_KEYS.get(identity_label)
        if not identity or len(numbers) < 12:
            continue

        raw[identity][current_option] = OptionSide(
            oi_buy_lot=as_int(numbers[6]),
            oi_buy_amount=as_int(numbers[7]),
            oi_sell_lot=as_int(numbers[8]),
            oi_sell_amount=as_int(numbers[9]),
        )

    if not any(raw[identity]["買權"].oi_buy_lot or raw[identity]["賣權"].oi_buy_lot for identity in IDENTITY_ORDER):
        raise ValueError(f"No {PRODUCT_NAME} rows were found on TAIFEX page.")

    row: dict[str, Any] = {
        "date": trade_date.isoformat(),
        "dateLabel": date_label(trade_date),
        "raw": {
            identity: {
                option: side.__dict__
                for option, side in sides.items()
            }
            for identity, sides in raw.items()
        },
    }

    for identity in IDENTITY_ORDER:
        call = raw[identity]["買權"]
        put = raw[identity]["賣權"]
        prefix = identity
        row[f"{prefix}BullLot"] = call.oi_buy_lot + put.oi_sell_lot
        row[f"{prefix}BullAmount"] = call.oi_buy_amount + put.oi_sell_amount
        row[f"{prefix}BearLot"] = put.oi_buy_lot + call.oi_sell_lot
        row[f"{prefix}BearAmount"] = put.oi_buy_amount + call.oi_sell_amount
        row[f"{prefix}NetLot"] = row[f"{prefix}BullLot"] - row[f"{prefix}BearLot"]
        row[f"{prefix}NetAmount"] = row[f"{prefix}BullAmount"] - row[f"{prefix}BearAmount"]

    return row


def attach_diffs(rows: list[dict[str, Any]]) -> None:
    metric_suffixes = ["BullLot", "BullAmount", "BearLot", "BearAmount", "NetLot", "NetAmount"]
    for index, row in enumerate(rows):
        previous = rows[index + 1] if index + 1 < len(rows) else None
        for identity in IDENTITY_ORDER:
            for suffix in metric_suffixes:
                key = f"{identity}{suffix}"
                value = as_int(row.get(key))
                diff = value - as_int(previous.get(key)) if previous else 0
                row[f"{key}Format"] = fmt_int(value)
                row[f"{key}Diff"] = diff
                row[f"{key}DiffFormat"] = fmt_signed(diff)


def empty_retail_indicator(last_error: str | None = None) -> dict[str, Any]:
    return {
        "source": RETAIL_SOURCE_LABEL,
        "sourceUrl": TAIFEX_FUT_CONTRACTS_URL,
        "marketSourceUrl": TAIFEX_FUT_DAILY_URL,
        "productId": MINI_FUTURES_MARKET_ID,
        "productName": MINI_FUTURES_NAME,
        "rows": [],
        "latest": None,
        "fetchedAt": None,
        "lastError": last_error,
    }


def empty_market_index(last_error: str | None = None) -> dict[str, Any]:
    return {
        "source": MARKET_INDEX_SOURCE_LABEL,
        "sourceUrl": TWSE_TAIEX_URL,
        "productId": "TAIEX",
        "productName": "加權指數",
        "rows": [],
        "latest": None,
        "fetchedAt": None,
        "lastError": last_error,
    }


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def tone_for_value(value: Any) -> str:
    numeric = safe_number(value)
    if numeric > 0:
        return "up"
    if numeric < 0:
        return "dn"
    return "neutral"


def score_market_signal(
    foreign_amount: Any,
    foreign_amount_diff: Any,
    foreign_lot: Any,
    retail_ratio: Any,
    market_change_pct: Any,
) -> int:
    amount = safe_number(foreign_amount)
    amount_diff = safe_number(foreign_amount_diff)
    lot = safe_number(foreign_lot)
    ratio = safe_number(retail_ratio)
    change_pct = safe_number(market_change_pct)

    score = 50.0
    score += 18 if amount > 0 else -18 if amount < 0 else 0
    score += 8 if amount_diff > 0 else -8 if amount_diff < 0 else 0
    score += 8 if lot > 0 else -8 if lot < 0 else 0
    score += 6 if change_pct > 0 else -6 if change_pct < 0 else 0
    if ratio >= 25:
        score -= 8
    elif ratio <= -25:
        score += 8
    if amount < 0 and ratio > 20:
        score -= 6
    elif amount > 0 and ratio < -20:
        score += 6
    return int(round(clamp(score, 0, 100)))


def normalized_signal_score(raw_score: Any) -> float:
    return round(clamp(safe_number(raw_score) / 100, 0, 1), 4)


def fmt_signal_percent(value: Any) -> str:
    return f"{safe_number(value) * 100:.0f}%"


def market_signal_breakdown(
    foreign_amount: Any,
    foreign_amount_diff: Any,
    foreign_lot: Any,
    retail_ratio: Any,
    market_change_pct: Any,
) -> list[dict[str, Any]]:
    amount = safe_number(foreign_amount)
    amount_diff = safe_number(foreign_amount_diff)
    lot = safe_number(foreign_lot)
    ratio = safe_number(retail_ratio)
    change_pct = safe_number(market_change_pct)
    def item(label: str, raw_points: int, reason: str, tone: str | None = None, show_sign: bool = True) -> dict[str, Any]:
        value = round(raw_points / 100, 4)
        if raw_points > 0 and show_sign:
            points_format = f"+{raw_points}%"
        elif raw_points < 0:
            points_format = f"{raw_points}%"
        else:
            points_format = f"{raw_points}%"
        return {
            "label": label,
            "points": value,
            "pointsFormat": points_format,
            "rawPoints": raw_points,
            "reason": reason,
            "tone": tone,
        }

    items: list[dict[str, Any]] = [
        item("中性基準", 50, "中性起點 50%", "neutral-text", False),
        item("外資合成金額", 18 if amount > 0 else -18 if amount < 0 else 0, "正值偏多，負值偏空"),
        item("外資金額日變化", 8 if amount_diff > 0 else -8 if amount_diff < 0 else 0, "金額增加加分，減少扣分"),
        item("外資口數淨額", 8 if lot > 0 else -8 if lot < 0 else 0, "口數正值加分，負值扣分"),
        item("大盤漲跌", 6 if change_pct > 0 else -6 if change_pct < 0 else 0, "大盤上漲加分，下跌扣分"),
    ]
    if ratio >= 25:
        items.append(item("散戶多空比", -8, "散戶偏多過熱扣分"))
    elif ratio <= -25:
        items.append(item("散戶多空比", 8, "散戶偏空過深加分"))
    else:
        items.append(item("散戶多空比", 0, "未達極端區"))
    if amount < 0 and ratio > 20:
        items.append(item("法人散戶背離", -6, "外資偏空且散戶偏多"))
    elif amount > 0 and ratio < -20:
        items.append(item("法人散戶背離", 6, "外資偏多且散戶偏空"))
    else:
        items.append(item("法人散戶背離", 0, "未觸發背離調整"))
    return items


def stance_from_score(score: int) -> tuple[str, str]:
    if score >= 68:
        return "偏多觀察", "up"
    if score <= 32:
        return "偏空防守", "dn"
    return "中性等待", "neutral"


def pct_change(next_value: Any, current_value: Any) -> float:
    current = safe_number(current_value)
    if current == 0:
        return 0.0
    return (safe_number(next_value) - current) / current * 100


def outcome_success(stance: str, next_return: float) -> bool:
    if stance == "偏多觀察":
        return next_return > 0
    if stance == "偏空防守":
        return next_return < 0
    return abs(next_return) < 0.35


def build_signal_stats(payload: dict[str, Any], current_insight: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows") or []
    retail_rows = (payload.get("retailIndicator") or {}).get("rows") or []
    market_rows = (payload.get("marketIndex") or {}).get("rows") or []
    retail_by_date = {row.get("dateLabel"): row for row in retail_rows}
    market_by_date = {row.get("dateLabel"): row for row in market_rows}
    samples: list[dict[str, Any]] = []

    for index in range(1, max(len(rows) - 1, 1)):
        row = rows[index]
        previous = rows[index + 1] if index + 1 < len(rows) else {}
        next_row = rows[index - 1]
        market_row = market_by_date.get(row.get("dateLabel")) or {}
        next_market = market_by_date.get(next_row.get("dateLabel")) or {}
        if not market_row or not next_market:
            continue
        signal_score = score_market_signal(
            row.get("foreignNetAmount"),
            row.get("foreignNetAmountDiff"),
            row.get("foreignNetLot"),
            (retail_by_date.get(row.get("dateLabel")) or {}).get("retailLongShortRatio"),
            market_row.get("changePercent"),
        )
        stance, tone = stance_from_score(signal_score)
        next_return = pct_change(next_market.get("close"), market_row.get("close"))
        samples.append({
            "dateLabel": row.get("dateLabel"),
            "nextDateLabel": next_row.get("dateLabel"),
            "rawScore": signal_score,
            "score": normalized_signal_score(signal_score),
            "scoreFormat": fmt_signal_percent(normalized_signal_score(signal_score)),
            "stance": stance,
            "tone": tone,
            "nextReturn": round(next_return, 2),
            "nextReturnFormat": fmt_signed_percent(next_return),
            "success": outcome_success(stance, next_return),
            "foreignAmount": row.get("foreignNetAmountFormat", fmt_int(row.get("foreignNetAmount"))),
            "foreignAmountChange": row.get("foreignNetAmountDiffFormat", fmt_signed(row.get("foreignNetAmountDiff"))),
            "previousForeignAmount": previous.get("foreignNetAmountFormat", "-"),
        })

    current_stance = current_insight.get("stance")
    similar = [sample for sample in samples if sample.get("stance") == current_stance]
    if not similar:
        similar = samples
    sample_size = len(similar)
    wins = sum(1 for sample in similar if sample.get("success"))
    avg_return = sum(float(sample.get("nextReturn") or 0) for sample in similar) / sample_size if sample_size else 0
    win_rate = wins / sample_size * 100 if sample_size else 0
    if sample_size < 3:
        reliability = "樣本不足"
    elif win_rate >= 60:
        reliability = "偏有效"
    elif win_rate <= 40:
        reliability = "反向參考"
    else:
        reliability = "普通"
    return {
        "window": f"近 {LOOKBACK_ROWS} 日",
        "method": "相同市場訊號隔日大盤方向統計",
        "sampleSize": sample_size,
        "wins": wins,
        "winRate": round(win_rate, 1),
        "winRateFormat": f"{win_rate:.1f}%",
        "avgNextReturn": round(avg_return, 2),
        "avgNextReturnFormat": fmt_signed_percent(avg_return),
        "reliability": reliability,
        "samples": similar[:5],
    }


def build_signal_alerts(payload: dict[str, Any], insight: dict[str, Any]) -> list[dict[str, str]]:
    latest = payload.get("latest") or {}
    retail_latest = (payload.get("retailIndicator") or {}).get("latest") or {}
    market_latest = (payload.get("marketIndex") or {}).get("latest") or {}
    alerts: list[dict[str, str]] = []
    raw_score = safe_number(insight.get("rawScore"), 50)
    foreign_amount = safe_number(latest.get("foreignNetAmount"))
    foreign_amount_diff = safe_number(latest.get("foreignNetAmountDiff"))
    retail_ratio = safe_number(retail_latest.get("retailLongShortRatio"))
    market_change_pct = safe_number(market_latest.get("changePercent"))

    if raw_score <= 20:
        alerts.append({"level": "high", "label": "極端偏空", "text": "市場訊號低於 20%，隔日優先觀察反彈失敗或續弱。"})
    elif raw_score >= 80:
        alerts.append({"level": "high", "label": "極端偏多", "text": "市場訊號高於 80%，隔日優先觀察追價延續性。"})
    if abs(foreign_amount_diff) >= 500000:
        alerts.append({"level": "medium", "label": "外資金額劇烈變化", "text": f"外資合成部位金額日變化 {latest.get('foreignNetAmountDiffFormat', fmt_signed(foreign_amount_diff))} 千元。"})
    if foreign_amount < 0 and retail_ratio >= 30:
        alerts.append({"level": "high", "label": "法人散戶背離", "text": "外資金額偏空但散戶多空比偏高，容易形成震盪或回檔壓力。"})
    if foreign_amount > 0 and retail_ratio <= -30:
        alerts.append({"level": "medium", "label": "反向擠壓觀察", "text": "外資金額偏多但散戶偏空，若大盤轉強可能出現追價修正。"})
    if abs(market_change_pct) < 0.2 and abs(foreign_amount_diff) >= 300000:
        alerts.append({"level": "medium", "label": "盤面平靜但籌碼移動", "text": "大盤漲跌不大，但外資合成部位已明顯移動。"})
    if not alerts:
        alerts.append({"level": "low", "label": "無極端警示", "text": "目前訊號未觸發極端條件，持續觀察下一筆日變化。"})
    return alerts[:4]


def build_market_insights(payload: dict[str, Any]) -> dict[str, Any]:
    latest = payload.get("latest") or {}
    rows = payload.get("rows") or []
    previous = rows[1] if len(rows) > 1 else {}
    retail_payload = payload.get("retailIndicator") or {}
    retail_latest = retail_payload.get("latest") or {}
    retail_rows = retail_payload.get("rows") or []
    retail_previous = retail_rows[1] if len(retail_rows) > 1 else {}
    market_latest = (payload.get("marketIndex") or {}).get("latest") or {}

    foreign_amount = safe_number(latest.get("foreignNetAmount"))
    foreign_amount_diff = safe_number(latest.get("foreignNetAmountDiff"))
    foreign_lot = safe_number(latest.get("foreignNetLot"))
    foreign_lot_diff = safe_number(latest.get("foreignNetLotDiff"))
    retail_ratio = safe_number(retail_latest.get("retailLongShortRatio"))
    retail_ratio_diff = safe_number(retail_latest.get("retailLongShortRatioDiff"))
    market_change_pct = safe_number(market_latest.get("changePercent"))

    raw_score = score_market_signal(foreign_amount, foreign_amount_diff, foreign_lot, retail_ratio, market_change_pct)
    score = normalized_signal_score(raw_score)
    stance, tone = stance_from_score(raw_score)

    agreement = 0
    if foreign_amount and foreign_lot and (foreign_amount > 0) == (foreign_lot > 0):
        agreement += 1
    if foreign_amount and market_change_pct and (foreign_amount > 0) == (market_change_pct > 0):
        agreement += 1
    if foreign_amount and retail_ratio and (foreign_amount > 0) != (retail_ratio > 0):
        agreement += 1
    confidence = "高" if agreement >= 2 else "中" if agreement == 1 else "低"

    if foreign_amount < 0 and retail_ratio > 20:
        summary = "外資合成部位偏空，散戶偏多，盤勢容易出現壓力或震盪。"
    elif foreign_amount > 0 and retail_ratio < -20:
        summary = "外資合成部位偏多，散戶偏空，籌碼方向偏向法人主導。"
    elif foreign_amount > 0:
        summary = "外資合成部位偏多，短線以追蹤延續性為主。"
    elif foreign_amount < 0:
        summary = "外資合成部位偏空，短線以風險控管與反彈強度為主。"
    else:
        summary = "外資合成部位接近中性，等待下一筆明確變化。"

    bullets = [
        f"外資選擇權合成部位金額 {latest.get('foreignNetAmountFormat', fmt_int(foreign_amount))} 千元，日變化 {latest.get('foreignNetAmountDiffFormat', fmt_signed(foreign_amount_diff))}。",
        f"外資口數淨額 {fmt_signed(foreign_lot)}，日變化 {fmt_signed(foreign_lot_diff)}。",
    ]
    if retail_latest:
        bullets.append(
            f"小台散戶多空比 {retail_latest.get('retailLongShortRatioFormat', '-')}，前值 {retail_previous.get('retailLongShortRatioFormat', '-')}，變化 {retail_latest.get('retailLongShortRatioDiffFormat', fmt_signed_percent(retail_ratio_diff))}。"
        )
    if market_latest:
        bullets.append(
            f"大盤收盤 {market_latest.get('closeFormat', '-')}，漲跌 {market_latest.get('changeFormat', '+0.00')} / {market_latest.get('changePercentFormat', '+0.00%')}。"
        )

    risks: list[str] = []
    if abs(foreign_amount_diff) > max(abs(safe_number(previous.get("foreignNetAmount"))) * 0.75, 300000):
        risks.append("外資合成部位金額日變化較大，隔日需觀察是否延續。")
    if retail_ratio >= 30:
        risks.append("散戶多空比偏高，若外資不同向，追價風險提高。")
    if retail_ratio <= -30:
        risks.append("散戶偏空過深，若外資轉多，容易出現反向修正。")
    if not risks:
        risks.append("目前未出現極端單一風險，重點觀察下一筆日變化。")

    return {
        "dateLabel": latest.get("dateLabel") or retail_latest.get("dateLabel") or market_latest.get("dateLabel"),
        "rawScore": raw_score,
        "rawScoreFormat": f"{raw_score}/100",
        "score": score,
        "scoreFormat": fmt_signal_percent(score),
        "scoreBreakdown": market_signal_breakdown(
            foreign_amount,
            foreign_amount_diff,
            foreign_lot,
            retail_ratio,
            market_change_pct,
        ),
        "stance": stance,
        "tone": tone,
        "confidence": confidence,
        "summary": summary,
        "bullets": bullets,
        "risks": risks,
        "drivers": [
            {
                "label": "外資合成金額",
                "value": latest.get("foreignNetAmountFormat", fmt_int(foreign_amount)),
                "previous": previous.get("foreignNetAmountFormat", fmt_int(previous.get("foreignNetAmount"))),
                "change": latest.get("foreignNetAmountDiffFormat", fmt_signed(foreign_amount_diff)),
                "tone": tone_for_value(foreign_amount),
            },
            {
                "label": "外資口數淨額",
                "value": fmt_signed(foreign_lot),
                "previous": fmt_signed(previous.get("foreignNetLot")),
                "change": fmt_signed(foreign_lot_diff),
                "tone": tone_for_value(foreign_lot),
            },
            {
                "label": "散戶多空比",
                "value": retail_latest.get("retailLongShortRatioFormat", "-"),
                "previous": retail_previous.get("retailLongShortRatioFormat", "-"),
                "change": retail_latest.get("retailLongShortRatioDiffFormat", fmt_signed_percent(retail_ratio_diff)),
                "tone": tone_for_value(retail_ratio),
            },
            {
                "label": "大盤漲跌",
                "value": market_latest.get("changePercentFormat", "-"),
                "previous": market_latest.get("previousCloseFormat", "-"),
                "change": market_latest.get("changeFormat", "-"),
                "tone": tone_for_value(market_change_pct),
            },
        ],
    }


def normalize_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("source", TAIFEX_SOURCE_LABEL)
    payload.setdefault("sourceUrl", TAIFEX_CALLS_PUTS_URL)
    payload.setdefault("productId", PRODUCT_ID)
    payload.setdefault("productName", PRODUCT_NAME)
    payload.setdefault("rows", [])
    payload.setdefault("latest", None)
    payload.setdefault("fetchedAt", None)

    retail = payload.get("retailIndicator")
    if not isinstance(retail, dict):
        payload["retailIndicator"] = empty_retail_indicator()
    else:
        normalized = empty_retail_indicator(retail.get("lastError"))
        normalized.update(retail)
        normalized["rows"] = normalized.get("rows") or []
        normalized["latest"] = normalized.get("latest") or (normalized["rows"][0] if normalized["rows"] else None)
        payload["retailIndicator"] = normalized

    market_index = payload.get("marketIndex")
    if not isinstance(market_index, dict):
        payload["marketIndex"] = empty_market_index()
    else:
        normalized_market = empty_market_index(market_index.get("lastError"))
        normalized_market.update(market_index)
        normalized_market["rows"] = normalized_market.get("rows") or []
        normalized_market["latest"] = normalized_market.get("latest") or (
            normalized_market["rows"][0] if normalized_market["rows"] else None
        )
        payload["marketIndex"] = normalized_market
    insights = build_market_insights(payload)
    insights["stats"] = build_signal_stats(payload, insights)
    insights["alerts"] = build_signal_alerts(payload, insights)
    payload["insights"] = insights
    return payload


class DataStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return normalize_payload({
                "source": TAIFEX_SOURCE_LABEL,
                "sourceUrl": TAIFEX_CALLS_PUTS_URL,
                "productName": PRODUCT_NAME,
                "rows": [],
                "latest": None,
                "fetchedAt": None,
            })
        with self.path.open("r", encoding="utf-8") as file:
            return normalize_payload(json.load(file))

    def save(self, payload: dict[str, Any]) -> None:
        with self.lock:
            ensure_dirs()
            tmp_path = self.path.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
            tmp_path.replace(self.path)


def chart_points(rows: list[dict[str, Any]], key: str, limit: int = LOOKBACK_ROWS) -> list[tuple[str, float]]:
    ordered = list(reversed(rows[:limit]))
    return [(row["dateLabel"], safe_number(row.get(key))) for row in ordered]


def retail_points(payload: dict[str, Any], key: str, limit: int = LOOKBACK_ROWS) -> list[tuple[str, float]]:
    rows = payload.get("retailIndicator", {}).get("rows", [])
    ordered = list(reversed(rows[:limit]))
    return [(row["dateLabel"], safe_number(row.get(key))) for row in ordered]


def scale_points(values: list[float], top: float, bottom: float) -> list[float]:
    if not values:
        return []
    min_value, max_value = min(values), max(values)
    if min_value == max_value:
        min_value -= 1
        max_value += 1
    return [bottom - ((value - min_value) / (max_value - min_value) * (bottom - top)) for value in values]


def draw_overview_chart_png(payload: dict[str, Any], path: Path) -> None:
    if Image is None or ImageDraw is None:
        return

    width, height = 1200, 675
    img = Image.new("RGB", (width, height), "#eef8ff")
    draw = ImageDraw.Draw(img)
    try:
        title_font = ImageFont.truetype("msjh.ttc", 31)
        label_font = ImageFont.truetype("msjh.ttc", 19)
        metric_font = ImageFont.truetype("msjh.ttc", 30)
        score_font = ImageFont.truetype("msjh.ttc", 70)
        signal_font = ImageFont.truetype("msjh.ttc", 46)
        small_font = ImageFont.truetype("msjh.ttc", 15)
        tiny_font = ImageFont.truetype("msjh.ttc", 13)
    except Exception:
        title_font = label_font = metric_font = score_font = signal_font = small_font = tiny_font = ImageFont.load_default()

    latest = payload.get("latest") or {}
    retail_payload = payload.get("retailIndicator", {})
    retail_latest = retail_payload.get("latest") or {}
    retail_error = retail_payload.get("lastError")
    market_latest = (payload.get("marketIndex") or {}).get("latest") or {}
    insights = payload.get("insights") or build_market_insights(payload)
    alerts = insights.get("alerts") or []
    first_alert = alerts[0] if alerts else {}

    has_retail = bool(retail_latest)
    score_text = insights.get("scoreFormat", fmt_signal_percent(insights.get("score")))
    stance = insights.get("stance") or "等待資料"
    tone = insights.get("tone") or "neutral"
    if tone == "up":
        tone_color = "#c84055"
        tone_bg = "#fff1f3"
    elif tone == "dn":
        tone_color = "#16875c"
        tone_bg = "#edf9f3"
    else:
        tone_color = "#475467"
        tone_bg = "#f2f4f7"

    def badge(x: int, y: int, text: str, fg: str, bg: str) -> None:
        w = max(92, len(text) * 18 + 28)
        draw.rounded_rectangle((x, y, x + w, y + 34), radius=8, fill=bg, outline="#d9e0ea")
        draw.text((x + 14, y + 7), text, fill=fg, font=small_font)

    def metric_color(value: Any, neutral: bool = False) -> str:
        if neutral:
            return "#172033"
        numeric = safe_number(str(value).replace("%", ""))
        if numeric > 0:
            return "#c84055"
        if numeric < 0:
            return "#16875c"
        return "#172033"

    def wrap_text(text: str, limit: int) -> list[str]:
        text = text or "-"
        return [text[i:i + limit] for i in range(0, len(text), limit)] or ["-"]

    draw.rounded_rectangle((24, 20, width - 24, height - 20), radius=16, fill="#f8fcff", outline="#d8e8f7")
    date_text = latest.get("dateLabel") or retail_latest.get("dateLabel") or market_latest.get("dateLabel") or "-"
    draw.text((48, 34), "DCapp Stock 盤後市場快照", fill="#172033", font=title_font)
    draw.text((48, 76), f"{date_text}｜資料來源 TWSE / TAIFEX", fill="#667085", font=small_font)
    badge(938, 38, stance, tone_color, tone_bg)
    badge(1060, 38, f"信心 {insights.get('confidence', '-')}", "#475467", "#f2f4f7")

    hero_y = 112
    draw.rounded_rectangle((48, hero_y, 328, hero_y + 174), radius=10, fill="#ffffff", outline="#cfe2f4")
    draw.text((68, hero_y + 20), "市場訊號", fill="#667085", font=small_font)
    draw.text((68, hero_y + 52), str(score_text), fill=tone_color, font=signal_font)
    draw.text((68, hero_y + 134), f"{stance}｜信心 {insights.get('confidence', '-')}", fill="#172033", font=label_font)

    summary_x = 348
    draw.rounded_rectangle((summary_x, hero_y, width - 48, hero_y + 174), radius=10, fill="#ffffff", outline="#cfe2f4")
    draw.text((summary_x + 18, hero_y + 18), "一眼判讀", fill="#667085", font=small_font)
    for line_index, line in enumerate(wrap_text(insights.get("summary", "等待資料產生判讀。"), 31)[:2]):
        draw.text((summary_x + 18, hero_y + 46 + line_index * 31), line, fill="#172033", font=label_font)
    alert_label = first_alert.get("label", "提醒")
    alert_text = first_alert.get("text", "目前無極端警示。")
    alert_level = first_alert.get("level", "low")
    alert_bg = "#fff1f3" if alert_level == "high" else "#fff6e8" if alert_level == "medium" else "#f2f4f7"
    alert_fg = "#c84055" if alert_level == "high" else "#ba6f12" if alert_level == "medium" else "#475467"
    draw.rounded_rectangle((summary_x + 18, hero_y + 112, width - 68, hero_y + 158), radius=8, fill=alert_bg, outline="#ffd0d7" if alert_level == "high" else "#f2d39b" if alert_level == "medium" else "#d9e0ea")
    draw.text((summary_x + 34, hero_y + 124), f"{alert_label}：{alert_text[:42]}", fill=alert_fg, font=small_font)

    card_y = 306
    card_h = 104
    gap = 12
    card_w = (width - 96 - gap * 3) // 4
    cards = [
        ("大盤收盤", market_latest.get("closeFormat", "-"), f"{market_latest.get('changeFormat', '+0.00')} / {market_latest.get('changePercentFormat', '+0.00%')}", True),
        ("外資合成金額", latest.get("foreignNetAmountFormat", "-"), f"日變化 {latest.get('foreignNetAmountDiffFormat', '+0')}", False),
        ("小台散戶多空比", retail_latest.get("retailLongShortRatioFormat", "-"), f"前值變化 {retail_latest.get('retailLongShortRatioDiffFormat', '+0.00%')}", False),
        ("散戶淨留倉", retail_latest.get("retailNetFormat", "-"), f"全體 {retail_latest.get('totalOpenInterestFormat', '-')}", False),
    ]
    for index, (label, value, sub, neutral) in enumerate(cards):
        x = 48 + index * (card_w + gap)
        draw.rounded_rectangle((x, card_y, x + card_w, card_y + card_h), radius=8, fill="#ffffff", outline="#d9e0ea")
        draw.text((x + 14, card_y + 12), label, fill="#667085", font=tiny_font)
        draw.text((x + 14, card_y + 36), str(value), fill=metric_color(value, neutral), font=metric_font)
        draw.text((x + 14, card_y + 76), str(sub)[:21], fill="#667085", font=tiny_font)

    status_y = 424
    status_paused = retail_error or not has_retail
    status_text = f"法人 {latest.get('dateLabel', '-')}；散戶 {retail_latest.get('dateLabel', '-') if has_retail else '-'}；每日 {payload.get('scheduler', {}).get('time', SCHEDULE_TIME)} 排程更新。"
    if status_paused:
        status_text = f"小台散戶資料暫停：{retail_error or '等待資料'}"
    draw.text((52, status_y), status_text[:96], fill="#667085", font=small_font)

    left, right = 90, width - 62
    top, bottom = 474, height - 64
    plot_h = bottom - top
    rows = list(reversed((payload.get("rows") or [])[:LOOKBACK_ROWS]))
    retail_rows = list(reversed((payload.get("retailIndicator", {}).get("rows") or [])[:LOOKBACK_ROWS]))
    market_rows = list(reversed((payload.get("marketIndex", {}).get("rows") or [])[:LOOKBACK_ROWS]))
    dates = [row.get("dateLabel", "") for row in rows]
    if not dates and retail_rows:
        dates = [row.get("dateLabel", "") for row in retail_rows]
    total = max(len(dates), 1)

    def x_at(index: int) -> float:
        return left + (right - left) * index / max(total - 1, 1)

    draw.text((48, 442), "30 日方向趨勢（標準化比較）", fill="#172033", font=label_font)
    for i in range(6):
        y = top + plot_h * i / 5
        draw.line((left, y, right, y), fill="#edf1f6", width=1)
    zero_y = top + plot_h / 2
    draw.line((left, zero_y, right, zero_y), fill="#9aa4b2", width=2)

    foreign_values = [safe_number(row.get("foreignNetAmount")) for row in rows]
    ratio_values = [safe_number(row.get("retailLongShortRatio")) for row in retail_rows]
    market_values = [safe_number(row.get("changePercent")) for row in market_rows]
    foreign_y = scale_points(foreign_values, top + 20, bottom - 20)
    ratio_y = scale_points(ratio_values, top + 20, bottom - 20)
    market_y = scale_points(market_values, top + 20, bottom - 20)

    if len(foreign_y) > 1:
        coords = [(x_at(i), foreign_y[i]) for i in range(len(foreign_y))]
        draw.line(coords, fill="#3368d8", width=4)
        draw.ellipse((coords[-1][0] - 5, coords[-1][1] - 5, coords[-1][0] + 5, coords[-1][1] + 5), fill="#3368d8")
    if len(ratio_y) > 1:
        coords = [(x_at(i), ratio_y[i]) for i in range(len(ratio_y))]
        draw.line(coords, fill="#c77818", width=4)
        draw.ellipse((coords[-1][0] - 5, coords[-1][1] - 5, coords[-1][0] + 5, coords[-1][1] + 5), fill="#c77818")
    if len(market_y) > 1:
        coords = [(x_at(i), market_y[i]) for i in range(len(market_y))]
        draw.line(coords, fill="#16875c", width=3)
        draw.ellipse((coords[-1][0] - 4, coords[-1][1] - 4, coords[-1][0] + 4, coords[-1][1] + 4), fill="#16875c")

    if dates:
        step = max(1, len(dates) // 6)
        for index in range(0, len(dates), step):
            draw.text((x_at(index) - 24, height - 58), dates[index][5:], fill="#667085", font=small_font)

    legend_x = 642
    for name, color in [("外資合成金額", "#3368d8"), ("散戶多空比", "#c77818"), ("大盤漲跌", "#16875c")]:
        draw.rounded_rectangle((legend_x, 447, legend_x + 18, 465), radius=4, fill=color)
        draw.text((legend_x + 26, 444), name, fill="#344054", font=tiny_font)
        legend_x += 170

    img.save(path)


def draw_chart_png(payload: dict[str, Any], path: Path, identity: str = "foreign") -> None:
    if Image is None or ImageDraw is None:
        return
    identity = identity if identity in IDENTITY_LABELS else "foreign"
    rows = payload.get("rows", [])
    latest = payload.get("latest") or {}
    label = IDENTITY_LABELS[identity]
    colors = IDENTITY_COLORS[identity]

    width, height = 1200, 675
    margin_left, margin_right, margin_top, margin_bottom = 96, 56, 96, 92
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom
    img = Image.new("RGB", (width, height), "#f5f7fb")
    draw = ImageDraw.Draw(img)

    try:
        title_font = ImageFont.truetype("msjh.ttc", 30)
        label_font = ImageFont.truetype("msjh.ttc", 18)
        small_font = ImageFont.truetype("msjh.ttc", 15)
    except Exception:
        title_font = label_font = small_font = ImageFont.load_default()

    draw.rectangle((0, 0, width, height), fill="#f5f7fb")
    draw.text((48, 30), f"{PRODUCT_NAME} 三大法人多空未平倉 - {label}", fill="#192231", font=title_font)
    draw.text(
        (48, 70),
        f"{latest.get('dateLabel', '尚無資料')}  淨額 {fmt_signed(latest.get(f'{identity}NetLot', 0))}  "
        f"日變化 {latest.get(f'{identity}NetLotDiffFormat', '+0')}",
        fill="#596579",
        font=label_font,
    )

    series = [
        (f"{label}多方", chart_points(rows, f"{identity}BullLot"), colors[0]),
        (f"{label}空方", chart_points(rows, f"{identity}BearLot"), colors[1]),
        (f"{label}淨額", chart_points(rows, f"{identity}NetLot"), colors[2]),
    ]
    all_values = [value for _, points, _ in series for _, value in points]
    if not all_values:
        draw.text((48, 180), "尚未取得資料", fill="#596579", font=label_font)
        img.save(path)
        return

    min_value, max_value = min(all_values), max(all_values)
    if min_value == max_value:
        min_value -= 1
        max_value += 1
    span = max_value - min_value
    min_value -= span * 0.08
    max_value += span * 0.08

    def x_at(i: int, total: int) -> float:
        return margin_left + (plot_w * i / max(total - 1, 1))

    def y_at(value: float) -> float:
        return margin_top + ((max_value - value) / (max_value - min_value) * plot_h)

    zero_y = y_at(0)
    if margin_top <= zero_y <= margin_top + plot_h:
        draw.line((margin_left, zero_y, width - margin_right, zero_y), fill="#9aa4b2", width=2)

    for i in range(6):
        y = margin_top + plot_h * i / 5
        value = max_value - (max_value - min_value) * i / 5
        draw.line((margin_left, y, width - margin_right, y), fill="#dce2ec", width=1)
        draw.text((24, y - 10), fmt_int(value), fill="#667085", font=small_font)

    labels = series[0][1]
    if labels:
        step = max(1, len(labels) // 6)
        for idx in range(0, len(labels), step):
            x = x_at(idx, len(labels))
            draw.text((x - 28, height - 58), labels[idx][0][5:], fill="#667085", font=small_font)

    for name, points, color in series:
        coords = [(x_at(i, len(points)), y_at(value)) for i, (_, value) in enumerate(points)]
        if len(coords) > 1:
            draw.line(coords, fill=color, width=4)
        for x, y in coords[-1:]:
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=color)

    legend_x = 48
    for name, _, color in series:
        draw.rounded_rectangle((legend_x, height - 38, legend_x + 18, height - 20), radius=4, fill=color)
        draw.text((legend_x + 26, height - 40), name, fill="#344054", font=small_font)
        legend_x += 170

    img.save(path)


def generate_static_files(payload: dict[str, Any]) -> None:
    ensure_dirs()
    for identity in IDENTITY_ORDER:
        draw_chart_png(payload, STATIC_DIR / f"{identity}-chart.png", identity)
    draw_overview_chart_png(payload, STATIC_DIR / "overview-chart.png")
    draw_overview_chart_png(payload, STATIC_DIR / "latest-chart.png")


def ensure_overview_chart(payload: dict[str, Any]) -> Path:
    chart_path = STATIC_DIR / "overview-chart.png"
    if not chart_path.exists():
        draw_overview_chart_png(payload, chart_path)
    return chart_path


def discord_summary(payload: dict[str, Any], identity: str = "foreign") -> str:
    latest = payload.get("latest") or {}
    if not latest:
        return "尚未取得臺指選擇權三大法人資料。"
    identity = identity if identity in IDENTITY_LABELS else "foreign"
    label = IDENTITY_LABELS[identity]
    market_latest = (payload.get("marketIndex") or {}).get("latest") or {}
    retail_payload = payload.get("retailIndicator", {})
    retail_latest = retail_payload.get("latest") or {}
    retail_error = retail_payload.get("lastError")
    insights = payload.get("insights") or build_market_insights(payload)
    alerts = insights.get("alerts") or []
    alert_line = ""
    if alerts:
        alert_line = f"重點提醒：{alerts[0].get('label', '提醒')} - {alerts[0].get('text', '')}\n"
    market_line = "大盤：尚未取得資料"
    if market_latest:
        market_line = (
            f"大盤收盤：{market_latest.get('closeFormat', '-')} "
            f"({market_latest.get('changeFormat', '+0.00')}, {market_latest.get('changePercentFormat', '+0.00%')})"
        )
    retail_line = f"小台散戶多空比：尚未取得資料{f'（{retail_error}）' if retail_error else ''}"
    if retail_latest:
        retail_line = (
            f"小台散戶多空比：{retail_latest.get('retailLongShortRatioFormat')} "
            f"({retail_latest.get('retailLongShortRatioDiffFormat', '+0.00%')}, {retail_latest.get('bias', '中性')})"
        )
    return (
        f"**{latest.get('dateLabel')} {PRODUCT_NAME} {label}多空未平倉**\n"
        f"{market_line}\n"
        f"多方口數：{latest.get(f'{identity}BullLotFormat', fmt_int(latest.get(f'{identity}BullLot')))} "
        f"({latest.get(f'{identity}BullLotDiffFormat', '+0')})   "
        f"空方口數：{latest.get(f'{identity}BearLotFormat', fmt_int(latest.get(f'{identity}BearLot')))} "
        f"({latest.get(f'{identity}BearLotDiffFormat', '+0')})   "
        f"淨額：{fmt_signed(latest.get(f'{identity}NetLot'))} "
        f"({latest.get(f'{identity}NetLotDiffFormat', '+0')})\n"
        f"{alert_line}"
        f"{insights.get('summary', '')}\n"
        f"{retail_line}"
    )


store = DataStore(DATA_DIR / "latest.json")
client = TaifexClient()
market_client = MarketIndexClient()
retail_client = RetailIndicatorClient()
last_error: str | None = None
last_scheduler_run: str | None = None
discord_client: Any = None


def refresh_data() -> dict[str, Any]:
    global last_error
    ensure_dirs()
    previous = store.load()
    payload = client.fetch_history(LOOKBACK_ROWS)
    latest_date = parse_taifex_date(payload["tradeDate"].replace("-", "/")) if payload.get("tradeDate") else None
    try:
        payload["marketIndex"] = market_client.fetch_history(
            LOOKBACK_ROWS,
            latest=latest_date,
            cached=previous.get("marketIndex"),
        )
    except Exception as exc:
        previous_market = previous.get("marketIndex") or {}
        if previous_market.get("source") == MARKET_INDEX_SOURCE_LABEL:
            market_fallback = dict(previous_market)
        else:
            market_fallback = empty_market_index()
            market_fallback["fetchedAt"] = now_taipei().isoformat(timespec="seconds")
        market_fallback["lastError"] = str(exc)
        payload["marketIndex"] = market_fallback
    try:
        payload["retailIndicator"] = retail_client.fetch_history(
            LOOKBACK_ROWS,
            latest=latest_date,
            cached=previous.get("retailIndicator"),
        )
    except Exception as exc:
        previous_retail = previous.get("retailIndicator") or {}
        if previous_retail.get("source") == RETAIL_SOURCE_LABEL:
            retail_fallback = dict(previous_retail)
        else:
            retail_fallback = empty_retail_indicator()
            retail_fallback["fetchedAt"] = now_taipei().isoformat(timespec="seconds")
        retail_fallback["lastError"] = str(exc)
        payload["retailIndicator"] = retail_fallback
    payload = normalize_payload(payload)
    store.save(payload)
    generate_static_files(payload)
    last_error = None
    return payload


async def send_discord_report(payload: dict[str, Any] | None = None, identity: str = "foreign") -> None:
    if payload is None:
        payload = store.load()
    if not DISCORD_CHANNEL_IDS:
        raise RuntimeError("DISCORD_CHANNEL_IDS is not configured.")
    if discord_client is None:
        raise RuntimeError("Discord bot is not running.")

    chart_path = ensure_overview_chart(payload)

    discord = require_discord()
    for channel_id in DISCORD_CHANNEL_IDS:
        channel = discord_client.get_channel(channel_id)
        if channel is None:
            channel = await discord_client.fetch_channel(channel_id)
        await channel.send(
            content=discord_summary(payload, identity),
            file=discord.File(str(chart_path), filename=chart_path.name) if chart_path.exists() else None,
            view=InvestorSwitchView(payload),
        )


def post_discord_rest_report(payload: dict[str, Any] | None = None, identity: str = "foreign") -> dict[str, Any]:
    if payload is None:
        payload = store.load()
    if not DISCORD_BOT_TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN is not configured.")
    if not DISCORD_CHANNEL_IDS:
        raise RuntimeError("DISCORD_CHANNEL_IDS is not configured.")

    identity = identity if identity in IDENTITY_LABELS else "foreign"
    chart_path = ensure_overview_chart(payload)

    boundary = f"----taifex-discord-{uuid.uuid4().hex}"
    body = bytearray()

    def add_part(name: str, data: bytes, content_type: str, filename: str | None = None) -> None:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        disposition = f'form-data; name="{name}"'
        if filename:
            disposition += f'; filename="{filename}"'
        body.extend(f"Content-Disposition: {disposition}\r\n".encode("utf-8"))
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        body.extend(data)
        body.extend(b"\r\n")

    message = {"content": discord_summary(payload, identity)}
    add_part("payload_json", json.dumps(message, ensure_ascii=False).encode("utf-8"), "application/json")
    if chart_path.exists():
        add_part("files[0]", chart_path.read_bytes(), "image/png", chart_path.name)
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    results = []
    for channel_id in DISCORD_CHANNEL_IDS:
        req = urllib.request.Request(
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            data=bytes(body),
            headers={
                "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "taifex-discord-datastock/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            results.append({
                "channelId": channel_id,
                "status": response.status,
                "body": json.loads(response_body) if response_body else {},
            })
    return {"status": results[-1]["status"] if results else 0, "results": results}


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
            if current.time() >= scheduled_at and last_scheduler_run != today_key:
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
    server_version = "TaifexDataStock/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html_text: str) -> None:
        body = html_text.encode("utf-8")
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
            self.send_json(
                {
                    **store.load(),
                    "scheduler": {
                        "timezone": TIMEZONE_NAME,
                        "time": SCHEDULE_TIME,
                        "lastRun": last_scheduler_run,
                        "lastError": last_error,
                        "discordBotConfigured": discord_configured(),
                        "discordChannelCount": len(DISCORD_CHANNEL_IDS),
                        "discordBotEnabled": DISCORD_BOT_ENABLED,
                    },
                }
            )
        elif parsed.path == "/chart.png":
            query = urllib.parse.parse_qs(parsed.query)
            identity = query.get("identity", [None])[0]
            chart_path = STATIC_DIR / "overview-chart.png"
            if identity in IDENTITY_LABELS:
                chart_path = STATIC_DIR / f"{identity}-chart.png"
            if not chart_path.exists():
                payload = store.load()
                if identity in IDENTITY_LABELS:
                    draw_chart_png(payload, chart_path, identity)
                else:
                    draw_overview_chart_png(payload, chart_path)
            self.send_file(chart_path, "image/png")
        elif parsed.path.startswith("/static/"):
            requested = (STATIC_DIR / parsed.path.removeprefix("/static/")).resolve()
            if STATIC_DIR.resolve() not in requested.parents and requested != STATIC_DIR.resolve():
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
                self.send_json({"ok": True, "latest": payload.get("latest"), "fetchedAt": payload.get("fetchedAt")})
            elif parsed.path == "/api/send-discord":
                query = urllib.parse.parse_qs(parsed.query)
                identity = query.get("identity", ["foreign"])[0]
                if identity not in IDENTITY_LABELS:
                    identity = "foreign"
                payload = store.load()
                if not payload.get("latest"):
                    payload = refresh_data()
                if discord_client:
                    asyncio.run_coroutine_threadsafe(send_discord_report(payload, identity), discord_client.loop)
                    self.send_json({"ok": True, "mode": "bot"})
                else:
                    result = post_discord_rest_report(payload, identity)
                    self.send_json({"ok": True, "mode": "rest", "discord": {"status": result["status"]}})
            else:
                self.send_error(HTTPStatus.NOT_FOUND.value)
        except Exception as exc:
            global last_error
            last_error = traceback.format_exc()
            status = HTTPStatus.BAD_REQUEST if isinstance(exc, RuntimeError) else HTTPStatus.INTERNAL_SERVER_ERROR
            self.send_json({"ok": False, "error": str(exc), "trace": last_error}, status)


def require_discord() -> Any:
    try:
        import discord
        from discord import app_commands
    except Exception as exc:
        raise RuntimeError("discord.py is required for bot mode. Install dependencies with: pip install -r requirements.txt") from exc
    return discord


def create_discord_bot() -> Any:
    discord = require_discord()
    from discord import app_commands
    globals()["app_commands"] = app_commands

    intents = discord.Intents.default()
    bot = discord.Client(intents=intents)
    tree = app_commands.CommandTree(bot)

    @bot.event
    async def on_ready() -> None:
        await tree.sync()
        print(f"Discord bot logged in as {bot.user}")

    @tree.command(name="stock_today", description="顯示最新臺指選擇權三大法人摘要")
    @app_commands.describe(investor="法人別")
    @app_commands.choices(
        investor=[
            app_commands.Choice(name="外資", value="foreign"),
            app_commands.Choice(name="投信", value="investmentTrust"),
            app_commands.Choice(name="自營商", value="dealer"),
        ]
    )
    async def stock_today(interaction: Any, investor: app_commands.Choice[str] | None = None) -> None:
        identity = investor.value if investor else "foreign"
        payload = store.load()
        await interaction.response.send_message(discord_summary(payload, identity), view=InvestorSwitchView(payload))

    @tree.command(name="stock_chart", description="傳送最新臺指選擇權三大法人圖表")
    @app_commands.describe(investor="法人別")
    @app_commands.choices(
        investor=[
            app_commands.Choice(name="外資", value="foreign"),
            app_commands.Choice(name="投信", value="investmentTrust"),
            app_commands.Choice(name="自營商", value="dealer"),
        ]
    )
    async def stock_chart(interaction: Any, investor: app_commands.Choice[str] | None = None) -> None:
        identity = investor.value if investor else "foreign"
        payload = store.load()
        chart_path = STATIC_DIR / f"{identity}-chart.png"
        if not chart_path.exists():
            draw_chart_png(payload, chart_path, identity)
        await interaction.response.send_message(
            content=discord_summary(payload, identity),
            file=discord.File(str(chart_path), filename=chart_path.name) if chart_path.exists() else None,
            view=InvestorSwitchView(payload),
        )

    @tree.command(name="stock_refresh", description="重新抓取期交所資料並更新圖表")
    async def stock_refresh(interaction: Any) -> None:
        await interaction.response.defer(thinking=True)
        try:
            payload = await asyncio.to_thread(refresh_data)
            await interaction.followup.send(discord_summary(payload), view=InvestorSwitchView(payload))
        except Exception as exc:
            await interaction.followup.send(f"更新失敗：{exc}")

    return bot


class InvestorSwitchView:
    def __new__(cls, payload: dict[str, Any]) -> Any:
        discord = require_discord()

        class _View(discord.ui.View):
            def __init__(self, data: dict[str, Any]) -> None:
                super().__init__(timeout=300)
                self.data = data

            async def _send_identity(self, interaction: Any, identity: str) -> None:
                chart_path = STATIC_DIR / f"{identity}-chart.png"
                if not chart_path.exists():
                    draw_chart_png(self.data, chart_path, identity)
                await interaction.response.send_message(
                    content=discord_summary(self.data, identity),
                    file=discord.File(str(chart_path), filename=chart_path.name) if chart_path.exists() else None,
                    ephemeral=True,
                )

            @discord.ui.button(label="外資", style=discord.ButtonStyle.primary)
            async def foreign_button(self, interaction: Any, button: Any) -> None:
                await self._send_identity(interaction, "foreign")

            @discord.ui.button(label="投信", style=discord.ButtonStyle.secondary)
            async def trust_button(self, interaction: Any, button: Any) -> None:
                await self._send_identity(interaction, "investmentTrust")

            @discord.ui.button(label="自營商", style=discord.ButtonStyle.secondary)
            async def dealer_button(self, interaction: Any, button: Any) -> None:
                await self._send_identity(interaction, "dealer")

        return _View(payload)


def load_index_html() -> str:
    return (BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8")


def run_web_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((DEFAULT_HOST, DEFAULT_PORT), AppHandler)
    print(f"Serving {APP_BASE_URL}")
    print(f"Daily refresh: {SCHEDULE_TIME} {TIMEZONE_NAME}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
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

    threading.Thread(target=scheduler_loop, daemon=True).start()
    run_web_server()

    if DISCORD_BOT_ENABLED and DISCORD_BOT_TOKEN:
        global discord_client
        try:
            discord_client = create_discord_bot()
            discord_client.run(DISCORD_BOT_TOKEN)
        except Exception:
            last_error = traceback.format_exc()
            print(last_error)
            print("Discord bot failed to start. Web server will keep running.")
            while True:
                time.sleep(3600)
    else:
        if not DISCORD_BOT_ENABLED:
            print("Discord bot disabled: DISCORD_BOT_ENABLED=0.")
        else:
            print("Discord bot disabled: DISCORD_BOT_TOKEN is not configured.")
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
