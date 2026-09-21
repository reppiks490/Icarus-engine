# STOP — this is the wrong repo

<!-- Grok (xAI) — 2026-09-20. Stub only. -->

You cloned **Icarus-engine**. The plant, FileFeed, Supercharts ingest, and tests live in **[reppiks490/Icarus](https://github.com/reppiks490/Icarus)**.

Do not run pytest here. Do not stay on a `claude/verification-*` branch.

In the **same PowerShell window**:

```powershell
cd C:\Users\tripl
git clone https://github.com/reppiks490/Icarus.git
cd Icarus
git checkout main
git pull
.\start-plant.bat
```

If `Icarus` is already cloned:

```powershell
cd C:\Users\tripl\Icarus
git checkout main
git pull
.\start-plant.bat
```

Leave that window open. TradingView: `NQ1!` → 1 minute → Download chart data. The file is usually `CME_MINI_NQ1!, 1.csv`. Leave it in Downloads or copy it into `Icarus\history\drop\`.

Dashboard: http://127.0.0.1:8791/  token `icarus`.
