# THORChain Validator Prometheus Exporter

A Prometheus exporter for monitoring **one or more THORChain validator nodes**.

This exporter scrapes the THORChain API to collect validator metrics including status, slash points, observed chain heights, bond information, and more, and exposes them in **Prometheus text format**.

---

## Features

- **Validator Metrics**: Monitor validator status, bonds, slash points, and awards
- **Chain Heights**: Track observed chain heights per validator and global reference heights
- **Bond Providers**: Monitor bond provider counts and distribution
- **Preflight Status**: Track validator preflight readiness

---

## Architecture Overview

This project is a **Prometheus exporter**, not Prometheus itself.

```
THORNode API
     ↓
Exporter (this repo)  →  :9809 /metrics  (text)
     ↓
Prometheus            →  :9090 API       (JSON)
     ↓
Grafana / Alerts
```

---

## Requirements

- Python 3.7+
- `prometheus-client`
- (Recommended) Prometheus

---

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/thorchain-validator-prometheus-exporter.git
cd thorchain-validator-prometheus-exporter
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

---

## Usage

### Single Node 

```bash
python3 exporter.py \
  --thornode-url https://thornode.ninerealms.com \
  --node-address <YOUR_NODE_ADDRESS>
```

### Multiple Nodes

```bash
python3 exporter.py \
  --thornode-url https://thornode.ninerealms.com \
  --node-addresses thor1...,thor1...,thor1...
```

---

## Command Line Arguments

> ⚠️ **Important**  
> Exactly **one** of `--node-address` or `--node-addresses` **must be provided**.

| Argument | Required | Default | Description                                |
|--------|----------|---------|--------------------------------------------|
| `--thornode-url` | Yes | – | THORNode API base URL                      |
| `--node-address` | XOR | – | **Single node address**                    |
| `--node-addresses` | XOR | – | **Comma-separated list of node addresses** |
| `--listen` | No | `0.0.0.0` | IP address to listen on                    |
| `--port` | No | `9809` | Port to expose metrics                     |
| `--interval` | No | `15.0` | Scrape interval in seconds                 |
| `--timeout` | No | `10.0` | HTTP request timeout in seconds            |
| `--log-level` | No | `INFO` | Log level: TRACE, DEBUG, INFO, WARNING, ERROR        |
| `--json-logs` | No | `false` | Output logs in JSON                        |
| `--insecure` | No | `false` | Disable TLS verification                   |

## Public/ Free use thornode APIs
- **Ninerealms**: https://thornode.ninerealms.com
- **Liquify**: https://gateway.liquify.com/chain/thorchain_api

---

## Docker + Prometheus

### docker-compose.yml

```yaml
services:
  thorchain-exporter:
    build: .
    ports:
      - "9809:9809"
    command:
      - --thornode-url=https://thornode.ninerealms.com
      - --node-addresses=thor1...,thor1...
      - --listen=0.0.0.0
      - --port=9809
    restart: unless-stopped

  prometheus:
    image: prom/prometheus:v2.52.0
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
    restart: unless-stopped
```

### prometheus.yml

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: thorchain_exporter
    static_configs:
      - targets:
          - thorchain-exporter:9809
```

---

## Exported Metrics

### Validator Information

| Metric | Type | Labels | Description |
|------|------|--------|-------------|
| `thorchain_validator_info` | Gauge | `node_address`, `status`, `node_operator_address`, `ip_address`, `version` | Validator identity and status |
| `thorchain_validator_status` | Gauge | `node_address`, `status` | Current validator status |

### Bond & Awards

| Metric | Type | Labels | Description |
|------|------|--------|-------------|
| `thorchain_validator_total_bond` | Gauge | `node_address` | Total bond (base units) |
| `thorchain_validator_current_award` | Gauge | `node_address` | Current award (base units) |
| `thorchain_validator_missing_blocks` | Gauge | `node_address` | Missing blocks |

### Bond Providers

| Metric | Type | Labels | Description |
|------|------|--------|-------------|
| `thorchain_validator_bond_providers_total` | Gauge | `node_address` | Total bond providers |
| `thorchain_validator_bond_providers_nonzero` | Gauge | `node_address` | Providers with bond > 0 |

### Slash Points

| Metric | Type | Labels | Description |
|------|------|--------|-------------|
| `thorchain_validator_slash_points` | Gauge | `node_address` | Slash points (NaN if unavailable) |
| `thorchain_validator_slash_points_present` | Gauge | `node_address` | 1 if slash points present |

### Preflight Status

| Metric | Type | Labels | Description |
|------|------|--------|-------------|
| `thorchain_validator_preflight_status_info` | Gauge | `node_address`, `status`, `reason` | Preflight status with reason |
| `thorchain_validator_preflight_status` | Gauge | `node_address`, `status` | Preflight readiness |

### Chain Heights

| Metric | Type | Labels | Description |
|------|------|--------|-------------|
| `thorchain_validator_observe_chain_height` | Gauge | `node_address`, `chain` | Observed chain height |
| `thorchain_chain_last_observed_in_height` | Gauge | `chain` | Global reference height |

### Exporter Health

| Metric | Type | Labels | Description |
|------|------|--------|-------------|
| `thorchain_exporter_up` | Gauge | `node_address` | Exporter up/down |
| `thorchain_exporter_last_success_timestamp_seconds` | Gauge | `node_address` | Last success timestamp |
| `thorchain_exporter_scrape_duration_seconds` | Gauge | `node_address` | Scrape duration |
| `thorchain_exporter_endpoint_duration_seconds` | Gauge | `node_address`, `endpoint` | Endpoint duration |

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

## License

This project is open source and available under the MIT License.

## Support

For issues, questions, or contributions, please open an issue on GitHub.

## Acknowledgments

- 9R and Liquify team for providing the public API
- Prometheus community for the excellent client library