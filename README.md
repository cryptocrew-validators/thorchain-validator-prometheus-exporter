# THORChain Validator Prometheus Exporter

A Prometheus exporter for monitoring THORChain validator nodes. This exporter scrapes the THORChain API to collect validator metrics including status, slash points, observed chain heights, bond information, and more.

## Features

- **Validator Metrics**: Monitor validator status, bonds, slash points, and awards
- **Chain Heights**: Track observed chain heights per validator and global reference heights
- **Bond Providers**: Monitor bond provider counts and distribution
- **Preflight Status**: Track validator preflight readiness
- **Health Monitoring**: Built-in exporter health metrics with uptime and scrape duration
- **Flexible Logging**: Support for JSON or key-value formatted logs with configurable log levels
- **Graceful Shutdown**: Proper signal handling for clean shutdowns
- **Stale Metric Cleanup**: Automatic removal of metrics for chains that are no longer observed

## Requirements

- Python 3.7+
- `prometheus-client` library

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

## Usage

### Basic Example

```bash
python3 exporter.py \
  --thornode-url https://thornode.ninerealms.com \
  --node-address <YOUR_NODE_ADDRESS>
```

### All Options

```bash
python3 exporter.py \
  --thornode-url https://thornode.ninerealms.com \
  --node-address <YOUR_NODE_ADDRESS> \
  --listen 0.0.0.0 \
  --port 9809 \
  --interval 15.0 \
  --timeout 10.0 \
  --log-level INFO \
  --json-logs
```

### Command Line Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--thornode-url` | Yes | - | THORNode API base URL (e.g., `https://thornode.ninerealms.com`) |
| `--node-address` | Yes | - | THORChain node address to monitor |
| `--listen` | No | `0.0.0.0` | IP address to listen on |
| `--port` | No | `9809` | Port to expose metrics on |
| `--interval` | No | `15.0` | Scrape interval in seconds |
| `--timeout` | No | `10.0` | HTTP request timeout in seconds |
| `--log-level` | No | `INFO` | Log level: TRACE, DEBUG, INFO, WARNING, ERROR |
| `--json-logs` | No | `false` | Output logs in JSON format |
| `--insecure` | No | `false` | Disable TLS verification |

## Exported Metrics

### Validator Information

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `thorchain_validator_info` | Gauge | `node_address`, `status`, `node_operator_address`, `ip_address`, `version` | Validator identity and status information (value always 1) |
| `thorchain_validator_status` | Gauge | `node_address`, `status` | Current validator status (value always 1) |
| `thorchain_validator_total_bond` | Gauge | `node_address` | Total bond amount in base units |
| `thorchain_validator_current_award` | Gauge | `node_address` | Current award in base units |
| `thorchain_validator_missing_blocks` | Gauge | `node_address` | Number of missing blocks |

### Bond Providers

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `thorchain_validator_bond_providers_total` | Gauge | `node_address` | Total count of bond providers |
| `thorchain_validator_bond_providers_nonzero` | Gauge | `node_address` | Count of bond providers with bond > 0 |

### Slash Points

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `thorchain_validator_slash_points` | Gauge | `node_address` | Validator slash points (NaN if unavailable) |
| `thorchain_validator_slash_points_present` | Gauge | `node_address` | 1 if slash_points field was found, 0 otherwise |

### Preflight Status

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `thorchain_validator_preflight_status_info` | Gauge | `node_address`, `status`, `reason` | Preflight status with reason (value always 1) |
| `thorchain_validator_preflight_status` | Gauge | `node_address`, `status` | Preflight status (value always 1) |

### Chain Heights

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `thorchain_validator_observe_chain_height` | Gauge | `node_address`, `chain` | Observed chain height per chain for this validator |
| `thorchain_chain_last_observed_in_height` | Gauge | `chain` | Global reference height per chain from `/thorchain/lastblock` |

### Exporter Health

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `thorchain_exporter_up` | Gauge | `node_address` | 1 if last scrape succeeded, 0 otherwise |
| `thorchain_exporter_last_success_timestamp_seconds` | Gauge | `node_address` | Unix timestamp of last successful scrape |
| `thorchain_exporter_scrape_duration_seconds` | Gauge | `node_address` | Duration of last scrape cycle in seconds |
| `thorchain_exporter_endpoint_duration_seconds` | Gauge | `node_address`, `endpoint` | Duration per endpoint (`node` or `lastblock`) |

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is open source and available under the MIT License.

## Support

For issues, questions, or contributions, please open an issue on GitHub.

## Acknowledgments

- 9R team for providing the public API
- Prometheus community for the excellent client library
