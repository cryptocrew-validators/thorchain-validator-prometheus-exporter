#!/usr/bin/env python3
"""
THORChain Prometheus exporter: node metadata + slash points + observe heights + global reference heights.

Scrapes:
  1) GET {THORNODE_URL}/thorchain/node/{NODE_ADDRESS}
  2) GET {THORNODE_URL}/thorchain/lastblock

Exports:
  thorchain_validator_info{node_address="...",status="Active",node_operator_address="...",ip_address="...",version="..."} 1
  thorchain_validator_status{node_address="...",status="Active"} 1
  thorchain_validator_total_bond{node_address="..."} <int>
  thorchain_validator_bond_providers_total{node_address="..."} <count>
  thorchain_validator_bond_providers_nonzero{node_address="..."} <count>
  thorchain_validator_current_award{node_address="..."} <int>
  thorchain_validator_preflight_status_info{node_address="...",status="Ready",reason="OK"} 1
  thorchain_validator_preflight_status{node_address="...",status="Ready"} 1
  thorchain_validator_missing_blocks{node_address="..."} <int>
  thorchain_validator_slash_points{node_address="..."} <value|NaN>
  thorchain_validator_slash_points_present{node_address="..."} <0|1>
  thorchain_validator_observe_chain_height{node_address="...",chain="..."} <height>
  thorchain_chain_last_observed_in_height{chain="..."} <height>
  thorchain_exporter_last_success_timestamp_seconds{node_address="..."} <timestamp>
  thorchain_exporter_scrape_duration_seconds{node_address="..."} <duration>
  thorchain_exporter_endpoint_duration_seconds{node_address="...",endpoint="node|lastblock"} <duration>
  thorchain_exporter_up{node_address="..."} <0|1>
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import signal
import ssl
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Set, Tuple

from prometheus_client import Gauge, start_http_server

LOG = logging.getLogger("thorchain_exporter")

# ---------------- Custom TRACE level ----------------
TRACE = 5
logging.addLevelName(TRACE, "TRACE")


def trace(self: logging.Logger, msg: str, *args: Any, **kwargs: Any) -> None:
    if self.isEnabledFor(TRACE):
        self._log(TRACE, msg, args, **kwargs)


logging.Logger.trace = trace  # type: ignore[attr-defined]


# ---------------- Logging ----------------

def configure_logging(level: str, json_logs: bool) -> None:
    reserved = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
        "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
        "relativeCreated", "thread", "threadName", "processName", "process",
    }

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            base = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
            for k, v in record.__dict__.items():
                if k in reserved:
                    continue
                try:
                    json.dumps({k: v})
                    base[k] = v
                except Exception:
                    base[k] = str(v)
            if record.exc_info:
                base["exc_info"] = self.formatException(record.exc_info)
            return json.dumps(base, ensure_ascii=False)

    class KeyValueFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created))
            base = f"{ts} {record.levelname} {record.name} - {record.getMessage()}"
            extras = []
            for k, v in record.__dict__.items():
                if k in reserved:
                    continue
                try:
                    s = str(v)
                except Exception:
                    s = "<unprintable>"
                if len(s) > 400:
                    s = s[:400] + "…"
                extras.append(f"{k}={s}")
            if extras:
                base += " | " + " ".join(extras)
            if record.exc_info:
                base += "\n" + self.formatException(record.exc_info)
            return base

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_logs else KeyValueFormatter())

    root = logging.getLogger()
    root.handlers = [handler]

    lvl = level.upper()
    if lvl == "TRACE":
        root.setLevel(TRACE)
    else:
        root.setLevel(getattr(logging, lvl, logging.INFO))


class GracefulShutdown:
    def __init__(self) -> None:
        self.stop = False

    def _handler(self, signum: int, frame: Any) -> None:
        self.stop = True
        LOG.info("Shutdown signal received", extra={"signal": signum})

    def install(self) -> None:
        signal.signal(signal.SIGINT, self._handler)
        signal.signal(signal.SIGTERM, self._handler)


# ---------------- Metrics ----------------
# Info metrics (strings as labels)
METRIC_VALIDATOR_INFO = Gauge(
    "thorchain_validator_info",
    "Static-ish validator identity/status info from /thorchain/node (labels carry values)",
    ["node_address", "status", "node_operator_address", "ip_address", "version"],
)
METRIC_VALIDATOR_STATUS = Gauge(
    "thorchain_validator_status",
    "Validator status from /thorchain/node expressed as label (value always 1 for current status)",
    ["node_address", "status"],
)
METRIC_PREFLIGHT_INFO = Gauge(
    "thorchain_validator_preflight_status_info",
    "Preflight status info from /thorchain/node (labels carry status/reason; value always 1)",
    ["node_address", "status", "reason"],
)
METRIC_PREFLIGHT_STATUS = Gauge(
    "thorchain_validator_preflight_status",
    "Preflight status from /thorchain/node expressed as label (value always 1 for current status)",
    ["node_address", "status"],
)

# Numeric node metrics
METRIC_SLASH_POINTS = Gauge(
    "thorchain_validator_slash_points",
    "THORChain validator slash points for the given node address (NaN if unavailable in payload)",
    ["node_address"],
)
METRIC_SLASH_POINTS_PRESENT = Gauge(
    "thorchain_validator_slash_points_present",
    "1 if slash_points field was found in /thorchain/node payload, else 0",
    ["node_address"],
)
METRIC_TOTAL_BOND = Gauge(
    "thorchain_validator_total_bond",
    "Total bond from /thorchain/node (base units as returned by API)",
    ["node_address"],
)
METRIC_BOND_PROVIDERS_TOTAL = Gauge(
    "thorchain_validator_bond_providers_total",
    "Count of bond providers in /thorchain/node bond_providers.providers",
    ["node_address"],
)
METRIC_BOND_PROVIDERS_NONZERO = Gauge(
    "thorchain_validator_bond_providers_nonzero",
    "Count of bond providers with bond > 0",
    ["node_address"],
)
METRIC_CURRENT_AWARD = Gauge(
    "thorchain_validator_current_award",
    "Current award from /thorchain/node (base units as returned by API)",
    ["node_address"],
)
METRIC_MISSING_BLOCKS = Gauge(
    "thorchain_validator_missing_blocks",
    "missing_blocks from /thorchain/node",
    ["node_address"],
)

# Heights
METRIC_OBSERVE_CHAIN_HEIGHT = Gauge(
    "thorchain_validator_observe_chain_height",
    "Observed chain height per chain from /thorchain/node/{node} (observe_chains)",
    ["node_address", "chain"],
)
METRIC_GLOBAL_LAST_OBS_IN = Gauge(
    "thorchain_chain_last_observed_in_height",
    "Global reference height per chain from /thorchain/lastblock (last_observed_in)",
    ["chain"],
)

# Exporter health/timing
METRIC_UP = Gauge(
    "thorchain_exporter_up",
    "1 if last full scrape cycle succeeded, 0 otherwise",
    ["node_address"],
)
METRIC_LAST_SUCCESS_TS = Gauge(
    "thorchain_exporter_last_success_timestamp_seconds",
    "Unix timestamp when exporter last completed a successful scrape cycle",
    ["node_address"],
)
METRIC_SCRAPE_DURATION = Gauge(
    "thorchain_exporter_scrape_duration_seconds",
    "Duration of the last full scrape cycle in seconds",
    ["node_address"],
)
METRIC_ENDPOINT_DURATION = Gauge(
    "thorchain_exporter_endpoint_duration_seconds",
    "Duration of the last scrape per endpoint",
    ["node_address", "endpoint"],
)


# ---------------- HTTP helpers ----------------

def _ssl_context(insecure: bool) -> Optional[ssl.SSLContext]:
    if not insecure:
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def http_get_json(url: str, timeout: float, insecure: bool, max_err_body: int = 800) -> Any:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "thorchain-exporter/3.0"},
        method="GET",
    )
    ctx = _ssl_context(insecure)

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read()
            dt = time.time() - t0
            LOG.trace(
                "HTTP GET ok",
                extra={"url": url, "status": getattr(resp, "status", None), "bytes": len(body), "duration_s": round(dt, 4)},
            )
            return json.loads(body.decode("utf-8"))

    except urllib.error.HTTPError as e:
        body_preview = ""
        try:
            body_preview = e.read().decode("utf-8", errors="replace")[:max_err_body]
        except Exception:
            body_preview = "<unavailable>"
        dt = time.time() - t0
        LOG.error(
            "HTTP error while fetching",
            extra={
                "url": url,
                "status": getattr(e, "code", None),
                "reason": getattr(e, "reason", None),
                "body_preview": body_preview,
                "duration_s": round(dt, 4),
            },
            exc_info=True,
        )
        raise

    except urllib.error.URLError as e:
        dt = time.time() - t0
        reason = getattr(e, "reason", e)
        LOG.error(
            "URL error while fetching",
            extra={"url": url, "reason": str(reason), "duration_s": round(dt, 4)},
            exc_info=True,
        )
        raise

    except json.JSONDecodeError as e:
        dt = time.time() - t0
        LOG.error(
            "JSON decode error",
            extra={"url": url, "error": str(e), "duration_s": round(dt, 4)},
            exc_info=True,
        )
        raise


# ---------------- Parsing helpers ----------------

def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    s = str(v)
    # keep label values bounded
    return s if len(s) <= 256 else s[:256] + "…"


def _parse_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def find_first_key_recursive(obj: Any, keys: Set[str], max_depth: int = 6) -> Optional[Any]:
    if max_depth < 0:
        return None
    if isinstance(obj, dict):
        for k in keys:
            if k in obj:
                return obj[k]
        for v in obj.values():
            found = find_first_key_recursive(v, keys, max_depth=max_depth - 1)
            if found is not None:
                return found
        return None
    if isinstance(obj, list):
        for item in obj:
            found = find_first_key_recursive(item, keys, max_depth=max_depth - 1)
            if found is not None:
                return found
        return None
    return None


def parse_slash_points_tolerant(payload: Dict[str, Any]) -> Tuple[Optional[int], bool]:
    candidate = find_first_key_recursive(payload, {"slash_points", "slashPoints", "slashpoints"}, max_depth=6)
    if candidate is None:
        return None, False
    val = _parse_int(candidate)
    return (val, val is not None)


def parse_observe_chains(payload: Dict[str, Any]) -> Dict[str, int]:
    oc = payload.get("observe_chains")
    if oc is None:
        return {}
    if not isinstance(oc, list):
        raise ValueError(f"observe_chains is not a list: {type(oc).__name__}")

    out: Dict[str, int] = {}
    for item in oc:
        if not isinstance(item, dict):
            continue
        chain = item.get("chain")
        height = item.get("height")
        if chain is None:
            continue
        h = _parse_int(height)
        if h is None:
            continue
        out[str(chain)] = h
    return out


def parse_global_lastblock(payload: Any) -> Dict[str, int]:
    if payload is None:
        return {}
    if not isinstance(payload, list):
        raise ValueError(f"/thorchain/lastblock payload is not a list: {type(payload).__name__}")
    out: Dict[str, int] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        chain = item.get("chain")
        last_obs = item.get("last_observed_in")
        if chain is None or last_obs is None:
            continue
        h = _parse_int(last_obs)
        if h is None:
            continue
        out[str(chain)] = h
    return out


def parse_bond_providers_counts(payload: Dict[str, Any]) -> Tuple[int, int]:
    """
    Returns: (total_providers, nonzero_providers)
    based on payload["bond_providers"]["providers"] where provider["bond"] is numeric string.
    """
    bp = payload.get("bond_providers")
    if not isinstance(bp, dict):
        return 0, 0
    providers = bp.get("providers")
    if not isinstance(providers, list):
        return 0, 0

    total = 0
    nonzero = 0
    for p in providers:
        if not isinstance(p, dict):
            continue
        total += 1
        bond = _parse_int(p.get("bond"))
        if bond is not None and bond > 0:
            nonzero += 1
    return total, nonzero


def parse_preflight(payload: Dict[str, Any]) -> Tuple[str, str]:
    ps = payload.get("preflight_status")
    if not isinstance(ps, dict):
        return "", ""
    return _safe_str(ps.get("status")), _safe_str(ps.get("reason"))


# ---------------- Scrapers ----------------

def scrape_node(thornode_url: str, node_address: str, timeout: float, insecure: bool) -> Dict[str, Any]:
    base = thornode_url.rstrip("/")
    url = f"{base}/thorchain/node/{node_address}"

    LOG.debug("Scraping node endpoint", extra={"url": url, "timeout_s": timeout})
    t0 = time.time()
    payload = http_get_json(url, timeout=timeout, insecure=insecure)
    dt = time.time() - t0
    METRIC_ENDPOINT_DURATION.labels(node_address, "node").set(dt)

    if not isinstance(payload, dict):
        raise ValueError(f"/thorchain/node payload is not an object: {type(payload).__name__}")

    LOG.debug(
        "Node payload received",
        extra={"url": url, "duration_s": round(dt, 4), "top_level_keys": sorted(list(payload.keys()))[:80]},
    )
    return payload


def scrape_global_lastblock(thornode_url: str, node_address: str, timeout: float, insecure: bool) -> Dict[str, int]:
    base = thornode_url.rstrip("/")
    url = f"{base}/thorchain/lastblock"

    LOG.debug("Scraping lastblock endpoint", extra={"url": url, "timeout_s": timeout})
    t0 = time.time()
    payload = http_get_json(url, timeout=timeout, insecure=insecure)
    dt = time.time() - t0
    METRIC_ENDPOINT_DURATION.labels(node_address, "lastblock").set(dt)

    global_heights = parse_global_lastblock(payload)
    LOG.debug("Lastblock parsed", extra={"url": url, "duration_s": round(dt, 4), "global_chains": len(global_heights)})
    LOG.trace("Global heights sample", extra={"sample": dict(list(global_heights.items())[:6])})
    return global_heights


# ---------------- Stale metric cleanup ----------------

def remove_stale_node_chain_metrics(node_address: str, previous: Set[str], current: Set[str]) -> None:
    for chain in (previous - current):
        try:
            METRIC_OBSERVE_CHAIN_HEIGHT.remove(node_address, chain)
        except KeyError:
            pass


def remove_stale_global_chain_metrics(previous: Set[str], current: Set[str]) -> None:
    for chain in (previous - current):
        try:
            METRIC_GLOBAL_LAST_OBS_IN.remove(chain)
        except KeyError:
            pass


# ---------------- Main loop ----------------

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--thornode-url", required=True)
    p.add_argument("--node-address", required=True)
    p.add_argument("--listen", default="0.0.0.0")
    p.add_argument("--port", type=int, default=9809)
    p.add_argument("--interval", type=float, default=15.0)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--log-level", default="INFO", help="TRACE, DEBUG, INFO, WARNING, ERROR")
    p.add_argument("--json-logs", action="store_true")
    p.add_argument("--insecure", action="store_true", help="Disable TLS verification (debug only)")
    args = p.parse_args()

    configure_logging(args.log_level, args.json_logs)

    shutdown = GracefulShutdown()
    shutdown.install()

    start_http_server(args.port, addr=args.listen)

    LOG.info(
        "Exporter started",
        extra={
            "listen": args.listen,
            "port": args.port,
            "thornode_url": args.thornode_url,
            "node_address": args.node_address,
            "interval_s": args.interval,
            "timeout_s": args.timeout,
            "insecure_tls": args.insecure,
            "json_logs": args.json_logs,
            "log_level": args.log_level,
        },
    )

    # Ensure base series exist immediately
    METRIC_UP.labels(args.node_address).set(0)
    METRIC_SLASH_POINTS.labels(args.node_address).set(math.nan)
    METRIC_SLASH_POINTS_PRESENT.labels(args.node_address).set(0)

    previous_node_chains: Set[str] = set()
    previous_global_chains: Set[str] = set()

    while not shutdown.stop:
        cycle_t0 = time.time()
        LOG.debug("Scrape cycle start", extra={"node_address": args.node_address})

        try:
            node_payload = scrape_node(
                thornode_url=args.thornode_url,
                node_address=args.node_address,
                timeout=args.timeout,
                insecure=args.insecure,
            )

            # Parse node fields requested
            node_addr = _safe_str(node_payload.get("node_address"))
            status = _safe_str(node_payload.get("status"))
            node_operator_addr = _safe_str(node_payload.get("node_operator_address"))
            total_bond = _parse_int(node_payload.get("total_bond"))
            ip_address = _safe_str(node_payload.get("ip_address"))
            version = _safe_str(node_payload.get("version"))
            current_award = _parse_int(node_payload.get("current_award"))
            missing_blocks = _parse_int(node_payload.get("missing_blocks"))

            preflight_status, preflight_reason = parse_preflight(node_payload)

            slash_points, slash_present = parse_slash_points_tolerant(node_payload)
            observe_heights = parse_observe_chains(node_payload)
            bp_total, bp_nonzero = parse_bond_providers_counts(node_payload)

            # Export INFO / string metrics
            METRIC_VALIDATOR_INFO.labels(
                node_address=node_addr or args.node_address,
                status=status,
                node_operator_address=node_operator_addr,
                ip_address=ip_address,
                version=version,
            ).set(1)

            # The "current" status time-series; remove old label values so it doesn't accumulate.
            # (Prometheus client does not support partial label deletion per-series easily without tracking;
            # we keep it simple by only setting the current status series.)
            METRIC_VALIDATOR_STATUS.labels(node_addr or args.node_address, status).set(1)

            METRIC_PREFLIGHT_INFO.labels(
                node_addr or args.node_address,
                preflight_status,
                preflight_reason,
            ).set(1)
            METRIC_PREFLIGHT_STATUS.labels(node_addr or args.node_address, preflight_status).set(1)

            # Export numeric node metrics
            if total_bond is not None:
                METRIC_TOTAL_BOND.labels(node_addr or args.node_address).set(total_bond)
            if current_award is not None:
                METRIC_CURRENT_AWARD.labels(node_addr or args.node_address).set(current_award)
            if missing_blocks is not None:
                METRIC_MISSING_BLOCKS.labels(node_addr or args.node_address).set(missing_blocks)

            METRIC_BOND_PROVIDERS_TOTAL.labels(node_addr or args.node_address).set(bp_total)
            METRIC_BOND_PROVIDERS_NONZERO.labels(node_addr or args.node_address).set(bp_nonzero)

            if slash_present and slash_points is not None:
                METRIC_SLASH_POINTS.labels(node_addr or args.node_address).set(slash_points)
                METRIC_SLASH_POINTS_PRESENT.labels(node_addr or args.node_address).set(1)
            else:
                METRIC_SLASH_POINTS.labels(node_addr or args.node_address).set(math.nan)
                METRIC_SLASH_POINTS_PRESENT.labels(node_addr or args.node_address).set(0)
                LOG.warning("slash_points not found in node payload; exporting NaN", extra={"node_address": args.node_address})

            # Export observe heights + stale cleanup
            current_node_chains = set(observe_heights.keys())
            remove_stale_node_chain_metrics(node_addr or args.node_address, previous_node_chains, current_node_chains)
            previous_node_chains = current_node_chains
            for chain, observed in observe_heights.items():
                METRIC_OBSERVE_CHAIN_HEIGHT.labels(node_addr or args.node_address, chain).set(observed)

            # Global heights
            global_heights = scrape_global_lastblock(
                thornode_url=args.thornode_url,
                node_address=args.node_address,
                timeout=args.timeout,
                insecure=args.insecure,
            )
            current_global = set(global_heights.keys())
            remove_stale_global_chain_metrics(previous_global_chains, current_global)
            previous_global_chains = current_global
            for chain, height in global_heights.items():
                METRIC_GLOBAL_LAST_OBS_IN.labels(chain).set(height)

            duration = time.time() - cycle_t0
            METRIC_SCRAPE_DURATION.labels(args.node_address).set(duration)
            METRIC_UP.labels(args.node_address).set(1)
            METRIC_LAST_SUCCESS_TS.labels(args.node_address).set(time.time())

            LOG.info(
                "Scrape cycle succeeded",
                extra={
                    "duration_s": round(duration, 4),
                    "node_address_field": node_addr,
                    "status": status,
                    "node_operator_address": node_operator_addr,
                    "ip_address": ip_address,
                    "version": version,
                    "total_bond": total_bond,
                    "bond_providers_total": bp_total,
                    "bond_providers_nonzero": bp_nonzero,
                    "current_award": current_award,
                    "preflight_status": preflight_status,
                    "preflight_reason": preflight_reason,
                    "missing_blocks": missing_blocks,
                    "observe_chains": len(observe_heights),
                    "global_chains": len(global_heights),
                },
            )

            LOG.trace("Observe heights sample", extra={"sample": dict(list(observe_heights.items())[:6])})

        except Exception as e:
            duration = time.time() - cycle_t0
            METRIC_SCRAPE_DURATION.labels(args.node_address).set(duration)
            METRIC_UP.labels(args.node_address).set(0)
            LOG.error("Scrape cycle failed", extra={"duration_s": round(duration, 4), "error": str(e)}, exc_info=True)

        # Sleep in small increments
        sleep_left = args.interval
        while sleep_left > 0 and not shutdown.stop:
            step = min(0.5, sleep_left)
            time.sleep(step)
            sleep_left -= step

    LOG.info("Exporter stopped", extra={"node_address": args.node_address})


if __name__ == "__main__":
    main()
