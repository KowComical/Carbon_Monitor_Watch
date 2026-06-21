# Carbon Monitor Watch

A lightweight dashboard for Carbon Monitor logs. The public static site only
ships the latest 14-day log window.

## Projects

- GRACED Database: `gpu104:/data3/kow/CM_Graced_Database/log/running_code`
- Cities Database: `gpu104:/data3/kow/CM_Cities_Database/log/running_code`
- China Database: `gpu104:/data3/kow/CM_China_Database/log/all_process`
- Power Database: `cm47:/data/xuanrenSong/CM_Power_Database/log`

## Run

```bash
python run.py --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765`.

## Refresh Mirrors

```bash
python tools/sync_logs.py
```

This updates `log_mirror/` and rebuilds the GitHub Pages data under
`static/data/`. Local mirrored log files older than the latest 14-day window are
deleted after each sync.

## Build Static Pages Data

```bash
python tools/build_static_data.py --days 14
```

The generated site lives in `static/`. GitHub Pages deploys that folder through
`.github/workflows/pages.yml`; `log_mirror/` and `logs/` are intentionally not
committed.

## Sync And Publish

After a GitHub remote is configured, this command syncs logs, rebuilds
`static/data/`, commits static changes, and pushes them:

```bash
bash tools/sync_and_publish.sh
```
