# Running Configurable Prometheus Exporter as a Service with systemd

This guide will help you set up your Configurable Prometheus exporter to run as a systemd service, allowing it to start automatically on boot and be managed with `systemctl` commands.

## Prerequisites

```bash
pip3 install flask gunicorn pyyaml
```

## Step 1: Create Configuration File

1. Create a configuration file (e.g., `exporter_config.yml`):

```yaml
scripts:
  - path: /path/to/your/script1.py
    args:
      - --format=prometheus
  
  - path: /path/to/your/script2.py
    args:
      - --metric-type=custom
```

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

## Step 4: Manage the Service

- To check the status of the service:

```bash
sudo systemctl status configurable-exporter
```

- To stop the service:

```bash
sudo systemctl stop configurable-exporter
```

- To restart the service:

```bash
sudo systemctl restart configurable-exporter
```

- To view logs:

```bash
sudo journalctl -u configurable-exporter
```

## Configuration File Format

The configuration file (`exporter_config.yml`) supports the following structure:

```yaml
default_timeout: 30  # Optional: override default 20s timeout for all scripts
max_workers: 5       # Optional: number of parallel workers (default: number of scripts, max 10)

scripts:
  - path: /absolute/path/to/script.py  # Absolute path to script
    args:                              # Optional arguments
      - --arg1
      - --arg2=value

  - path: ../relative/path/script.py   # Relative path to script
    args:
      - --format=prometheus
    timeout: 60                        # Optional: per-script timeout override
```

**Configuration Options:**

- `default_timeout`: Global timeout in seconds for all scripts (default: 20s)
- `max_workers`: Maximum number of scripts to run in parallel (default: number of scripts, capped at 10)
- `scripts`: List of scripts to execute
  - `path`: Path to the script (absolute or relative to config file)
  - `args`: Optional list of command-line arguments
  - `timeout`: Optional per-script timeout override

**Note:** Scripts are executed in parallel for better performance. The output is combined in the order scripts are defined in the configuration file.

## Summary

Your Configurable Prometheus exporter will now run as a managed service, automatically starting on boot and restarting if it encounters issues. The service will execute all scripts defined in the configuration file and combine their outputs when the `/metrics` endpoint is accessed.
