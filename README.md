# Running Configurable Prometheus Exporter as a Service with systemd

This guide will help you set up your Configurable Prometheus exporter to run as a systemd service, allowing it to start automatically on boot and be managed with `systemctl` commands.

## Prerequisites

```bash
pip3 install -r requirements.txt
```

## Step 1: Create Configuration File

The configuration file (`exporter_config.yml`) supports the following structure:

```yaml
instance_id: name1          # Optional: tag all metrics with this label
port: 9092                  # Optional: override default port (9092)
default_timeout: 30         # Optional: override default 20s timeout for all scripts
max_workers: 5              # Optional: number of parallel workers (default: number of scripts, max 10)
add_labels:                 # Optional: global labels added to every metric
  env: production

scripts:
  - path: /path/to/your/script1.py
    args:
      - --format=prometheus
    add_labels:             # Optional: per-script labels (merged with global add_labels)
      id: "1"
      region: us-east

  - path: ../relative/path/script2.py
    args:
      - --metric-type=custom
    timeout: 60
    add_labels:
      id: "2"
```

### Configuration Options

| Key | Level | Description |
|-----|-------|-------------|
| `instance_id` | global | Adds `{instance_id="your_value"}` to every metric. Shorthand for a single global label. |
| `add_labels` | global / per-script | Map of `key: value` labels to inject into every metric. Per-script labels are merged with global ones; per-script values win on conflict. |
| `port` | global | Port for the HTTP `/metrics` endpoint. CLI `--port` overrides this. |
| `default_timeout` | global | Script timeout in seconds (default: 20s). |
| `max_workers` | global | Number of scripts to run in parallel (default: script count, max 10). |
| `args` | per-script | List of arguments passed to the script. |
| `timeout` | per-script | Per-script timeout override. |

---

## Step 2: Create a systemd Service File

1. Open a new service file for editing:

```bash
sudo nano /etc/systemd/system/configurable-exporter.service
```

2. Add the following configuration to the file:

```ini
[Unit]
Description=Configurable Prometheus Exporter Service
After=network.target

[Service]
User=your_username
WorkingDirectory=/path/to/your/exporter
ExecStart=/usr/bin/python3 configurable_exporter.py --config /path/to/your/exporter_config.yml
Restart=always
Environment="PYTHONPATH=/path/to/your/exporter"

[Install]
WantedBy=multi-user.target
```

Replace:
- `your_username` with the username that should run the service
- `/path/to/your/exporter` with the path to the directory containing `configurable_exporter.py`
- `/path/to/your/exporter_config.yml` with the path to your configuration file

This configuration:
- Runs Gunicorn with 4 workers
- Binds to all interfaces on port `9092`
- Loads configuration from the specified YAML file
- Restarts the service automatically if it fails

## Step 3: Reload systemd and Start the Service

1. Reload the systemd daemon to recognize the new service file:

```bash
sudo systemctl daemon-reload
```

2. Start the Configurable Prometheus exporter service:

```bash
sudo systemctl start configurable-exporter
```

3. Enable it to start on boot:

```bash
sudo systemctl enable configurable-exporter
```

**Note:** Scripts are executed in parallel for better performance. The output is combined in the order scripts are defined in the configuration file.

## Summary

Your Configurable Prometheus exporter will now run as a managed service, automatically starting on boot and restarting if it encounters issues. The service will execute all scripts defined in the configuration file and combine their outputs when the `/metrics` endpoint is accessed.
