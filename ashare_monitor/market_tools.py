"""Bounded security discovery and validated, atomic local CSV imports.

The public search is a best-effort name/code directory, not verified trading
metadata. Imported files never enable live or demonstration account trading.
"""
from __future__ import annotations

import csv
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .data import DEFAULT_WATCHLIST, _EXAMPLES, security_info, validate_candles
from .rules import CALENDAR_YEARS

CSV_MAX_BYTES = 1_000_000
CSV_MAX_ROWS = 15000
REQUIRED_FIELDS = ("date", "open", "high", "low", "close", "volume")
OPTIONAL_FIELDS = ("amount", "adjustment", "raw_open", "raw_high", "raw_low", "raw_close")
_DIRECTORY = {**{code: info[0] for code, info in _EXAMPLES.items()},
              "600000": "浦发银行", "601166": "兴业银行", "601398": "工商银行",
              "601939": "建设银行", "601288": "农业银行", "601988": "中国银行",
              "600030": "中信证券", "600900": "长江电力", "601088": "中国神华",
              "600887": "伊利股份", "000858": "五粮液", "002415": "海康威视",
              "600276": "恒瑞医药", "300059": "东方财富", "002475": "立讯精密",
              "688012": "中微公司", "688008": "澜起科技", "601899": "紫金矿业",
              "600309": "万华化学", "600050": "中国联通"}


def csv_template():
    """Illustrative rows, explicitly not a price feed or a strategy sample."""
    return ("date,open,high,low,close,volume,amount,adjustment\n"
            "2026-10-08,10.00,10.20,9.90,10.10,100000,1005000,none\n"
            "2026-10-09,10.10,10.30,10.00,10.20,120000,1218000,none\n")


def _error(result, line, field, message):
    if len(result["errors"]) < 100:
        result["errors"].append({"line": line, "field": field, "message": message})


def _row_field(message):
    for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
        if field in message:
            return field
    if any(word in message for word in ("日期", "休市", "周末", "日历", "交易日")):
        return "date"
    if any(word in message for word in ("最高", "最低", "价格")):
        return "OHLC"
    return "row"


def validate_csv_import(code, text, as_of=None):
    """Return errors with CSV physical line numbers; never writes any data."""
    result = {"valid": False, "code": code, "fields": [], "row_count": 0,
              "first_date": None, "last_date": None, "adjustment": None,
              "calendar_unverified_years": [], "errors": [], "warnings": []}
    try:
        security_info(code)
    except ValueError as exc:
        _error(result, None, "code", str(exc))
        return result
    if not isinstance(text, str):
        _error(result, None, "file", "CSV 内容必须是 UTF-8 文本")
        return result
    if len(text.encode("utf-8")) > CSV_MAX_BYTES:
        _error(result, None, "file", "单股 CSV 导入不得超过 1 MB")
        return result
    if "\x00" in text:
        _error(result, None, "file", "CSV 不得包含 NUL 字符")
        return result
    if as_of is not None:
        try:
            from .data import _parse_date
            _parse_date(as_of)
        except ValueError as exc:
            _error(result, None, "as_of", str(exc))
            return result
    try:
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff"), newline=""), strict=True)
        fields = reader.fieldnames or []
        result["fields"] = fields
        missing = set(REQUIRED_FIELDS) - set(fields)
        if missing:
            _error(result, 1, "header", "CSV 缺少必需列：" + ",".join(sorted(missing)))
        if len(fields) != len(set(fields)):
            _error(result, 1, "header", "CSV 列名不得重复")
        unknown = set(fields) - set(REQUIRED_FIELDS + OPTIONAL_FIELDS)
        if unknown:
            _error(result, 1, "header", "不支持的列：" + ",".join(sorted(unknown)))
        if result["errors"]:
            return result
        rows = []
        for row in reader:
            line = reader.line_num
            if len(rows) >= CSV_MAX_ROWS:
                _error(result, line, "file", f"单股 CSV 不得超过 {CSV_MAX_ROWS} 行")
                break
            rows.append((line, row))
            if None in row or any(value is None for value in row.values()):
                _error(result, line, "row", "该行列数与表头不一致")
        result["row_count"] = len(rows)
    except (csv.Error, UnicodeError) as exc:
        _error(result, getattr(locals().get("reader"), "line_num", None), "file", "CSV 语法无效")
        return result
    if not rows:
        _error(result, 2, "row", "CSV 没有日线记录")
        return result
    adjustments = set()
    previous = None
    years = set()
    raw_fields = tuple("raw_" + field for field in ("open", "high", "low", "close"))
    raw_declared = bool(set(raw_fields) & set(fields))
    for line, row in rows:
        adjustment = (row.get("adjustment") or "").strip().lower()
        adjustments.add(adjustment)
        if adjustment not in {"", "none", "qfq"}:
            _error(result, line, "adjustment", "复权口径仅支持 none 或 qfq")
        try:
            parsed = validate_candles([{**row, "amount": row.get("amount") or 0}], as_of)[0]
            day = parsed["date"]
            if previous is not None and day <= previous:
                _error(result, line, "date", "日线日期必须升序且不得重复")
            previous = day
            years.add(int(day[:4]))
            if result["first_date"] is None:
                result["first_date"] = day
            result["last_date"] = day
            if raw_declared:
                raw_row = {**parsed, **{field: row.get("raw_" + field) for field in ("open", "high", "low", "close")}}
                try:
                    validate_candles([raw_row], as_of)
                except ValueError as exc:
                    _error(result, line, "raw_OHLC", "原价列不完整或无效：" + str(exc))
        except ValueError as exc:
            _error(result, line, _row_field(str(exc)), str(exc))
    if len(adjustments) != 1:
        _error(result, None, "adjustment", "所有日线须采用同一复权口径，不得混用或部分省略")
    result["adjustment"] = next(iter(adjustments)) if len(adjustments) == 1 else None
    if adjustments == {""}:
        result["warnings"].append("未声明复权口径；仅用于指标研究，不生成可靠原价情景和历史成交。")
    if adjustments == {"qfq"} and not raw_declared:
        result["warnings"].append("前复权数据没有独立 raw_open/raw_high/raw_low/raw_close；不能用于原价成交回放。")
    if len(rows) < 120:
        result["warnings"].append("历史不足 120 根日线，部分指标、预热或策略验证可能没有足够样本。")
    result["calendar_unverified_years"] = sorted(years - CALENDAR_YEARS)
    if result["calendar_unverified_years"]:
        result["warnings"].append("交易日历未覆盖 " + "、".join(map(str, result["calendar_unverified_years"])) +
                                  " 年；仅校验周末和行情格式，不认定为可模拟成交的交易日。")
    result["valid"] = not result["errors"]
    return result


def _is_link(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def commit_csv_import(root, code, text, overwrite=False):
    """Atomically save a validated six-digit CSV in the app-owned import folder.

    Existing different content needs explicit overwrite=True. There are no
    caller-controlled filenames, path disclosures or links in saved results.
    """
    checked = validate_csv_import(code, text)
    if not checked["valid"]:
        raise ValueError("CSV 校验未通过：" + checked["errors"][0]["message"])
    if type(overwrite) is not bool:
        raise ValueError("overwrite 必须是布尔值")
    root = Path(root).absolute()
    if any(_is_link(parent) for parent in (root, *root.parents)):
        raise ValueError("CSV 固定目录不得通过符号链接或目录联接访问")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve(strict=True)
    target = root / (code + ".csv")
    if _is_link(target) or (target.exists() and not target.is_file()):
        raise ValueError("CSV 目标不得是链接或其他特殊文件")
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if target.exists() and not overwrite:
        if target.stat().st_size <= CSV_MAX_BYTES and target.read_text(encoding="utf-8-sig") == normalized:
            return {**checked, "saved": True, "unchanged": True, "filename": target.name}
        raise ValueError("此代码已有 CSV；勾选确认覆盖后再导入，现有文件未改动")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", suffix=".tmp", prefix=".csv-import-", dir=root, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(normalized)
            handle.flush()
            os.fsync(handle.fileno())
        if _is_link(target):
            raise ValueError("CSV 目标被替换为链接，导入已取消")
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return {**checked, "saved": True, "unchanged": False, "filename": target.name}


def _security_result(code, name, source):
    stock = security_info(code)
    return {key: stock[key] for key in ("code", "exchange", "board")} | {
        "name": name or code, "source": source, "metadata_verified": False,
        "listing_date": None, "risk_warning": None, "demo_tradable": code in _EXAMPLES,
        "research_only": code not in _EXAMPLES,
        "notice": "目录匹配不代表交易元数据已核实；演示交易仅限预置的八只合成样本。"}


def _remote_search(query):
    params = urlencode({"input": query, "type": "14", "count": "20"})
    request = Request("https://searchapi.eastmoney.com/api/suggest/get?" + params,
                      headers={"User-Agent": "AshareResearch/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=2) as response:
        data = response.read(512001)
    if len(data) > 512000:
        raise ValueError("证券目录响应过大")
    payload = json.loads(data.decode("utf-8"))
    return payload.get("QuotationCodeTable", {}).get("Data", [])


def search_securities(query):
    if not isinstance(query, str) or len(query) > 32 or any(ord(char) < 32 for char in query):
        raise ValueError("搜索词须为不超过 32 字符的代码或名称")
    query = query.strip()
    items = {code: _security_result(code, name, "本地常见证券目录（非完整市场）")
             for code, name in _DIRECTORY.items() if not query or query in code or query.casefold() in name.casefold()}
    source, warning = "本地预置目录", "上市状态、风险警示与权限需另行核实；新增股票可研究，不自动获得模拟交易资格。"
    # Fast local matches keep the common picker offline and responsive.
    if query and not items:
        try:
            for row in _remote_search(query):
                code, name = str(row.get("Code", "")), str(row.get("Name", ""))[:80]
                try:
                    item = _security_result(code, name, "东方财富公开证券搜索（未独立核实）")
                except ValueError:
                    continue
                items[code] = item
            if items:
                source = "东方财富公开证券搜索"
        except Exception:
            warning = "公开搜索暂不可用，已返回本地匹配；" + warning
        if not items and re.fullmatch(r"\d{6}", query):
            try:
                items[query] = _security_result(query, query, "代码前缀识别（未确认证券存在）")
                warning = "仅识别代码格式，尚未确认该证券存在或处于上市状态；" + warning
            except ValueError:
                pass
    return {"items": list(items.values())[:30], "source": source, "warning": warning}


def watchlist_templates():
    return deepcopy([
        {"id": "demo", "name": "预置八股演示", "codes": DEFAULT_WATCHLIST,
         "description": "唯一提供已核实演示元数据的合成行情组合；不是投资推荐。"},
        {"id": "banks", "name": "银行研究", "codes": ["600036", "600000", "601166", "601398", "601939", "601288", "601988"],
         "description": "常见行业研究示例；新增股票只研究，真实交易元数据未核实。"},
        {"id": "technology", "name": "科技制造研究", "codes": ["688981", "688012", "688008", "002475", "002415", "300750"],
         "description": "覆盖主板、创业板与科创板；权限、上市及风险状态需另行核实。"},
    ])
