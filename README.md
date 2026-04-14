# IronFlet — Bilingual Weight Training Tracker

<div align="center">

![Project](https://img.shields.io/badge/Project-IronFlet-blue?style=for-the-badge)
![Version](https://img.shields.io/badge/Version-0.1.0-green?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-yellow?style=for-the-badge&logo=python&logoColor=white)
![Flet](https://img.shields.io/badge/Flet-0.28-7F52FF?style=for-the-badge&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)
![Platform](https://img.shields.io/badge/Platform-Android%20%7C%20Linux%20%7C%20Web-lightgrey?style=for-the-badge)

**Offline-first fitness tracker with 7 periodized routines, 68 annotated exercises and animated technique images — one Python codebase, three platforms.**

**Tracker de entrenamiento offline con 7 rutinas periodizadas, 68 ejercicios con imágenes animadas e instrucciones paso a paso — un único código Python que corre como APK, escritorio y web.**

---

### Choose Your Language / Elige tu idioma

<p align="center">
  <a href="README.en.md">
    <img src="https://img.shields.io/badge/English-Documentation-blue?style=for-the-badge&logo=markdown" alt="English Documentation" height="50">
  </a>
  &nbsp;&nbsp;&nbsp;
  <a href="README.es.md">
    <img src="https://img.shields.io/badge/Espa%C3%B1ol-Documentaci%C3%B3n-red?style=for-the-badge&logo=markdown" alt="Documentacion en Espanol" height="50">
  </a>
</p>

---

### Architecture Overview

```mermaid
graph TD
    USER["🖥️ User"]
    subgraph APP["📱 IronFlet Flet app"]
        NAV["Navigation<br/>5 tabs + Settings"]
        HOME["🏠 Home"]
        PLAN["📅 Plan"]
        TRAIN["💪 Train"]
        BROWSE["🔍 Browse"]
        HIST["📊 History"]
        PROF["⚙️ Settings"]
    end
    SQLITE[("🗄️ SQLite<br/>ironflet.db")]
    CACHE[("📸 Image cache<br/>exercises/")]
    GH["📦 GitHub Release<br/>exercises.tar.gz"]
    FEDB["🌐 Free Exercise DB<br/>Unlicense"]

    USER ---> NAV
    NAV --> HOME
    NAV --> PLAN
    NAV --> TRAIN
    NAV --> BROWSE
    NAV --> HIST
    NAV --> PROF
    TRAIN -->|workouts| SQLITE
    PROF -->|weights, backup| SQLITE
    HIST -->|reads| SQLITE
    BROWSE -->|thumbnails| CACHE
    TRAIN -.->|animated frames| CACHE
    PROF -.->|first-run download| GH
    GH -.->|derived from| FEDB

    style USER fill:#fff4e6,stroke:#e8590c,stroke-width:2px
    style APP fill:#e7f5ff,stroke:#1971c2,stroke-width:2px
    style NAV fill:#d0ebff,stroke:#1971c2,stroke-width:2px
    style HOME fill:#d0ebff,stroke:#1971c2,stroke-width:2px
    style PLAN fill:#d0ebff,stroke:#1971c2,stroke-width:2px
    style TRAIN fill:#d0ebff,stroke:#1971c2,stroke-width:2px
    style BROWSE fill:#d0ebff,stroke:#1971c2,stroke-width:2px
    style HIST fill:#d0ebff,stroke:#1971c2,stroke-width:2px
    style PROF fill:#d0ebff,stroke:#1971c2,stroke-width:2px
    style SQLITE fill:#fff3bf,stroke:#f08c00
    style CACHE fill:#fff3bf,stroke:#f08c00,stroke-width:3px
    style GH fill:#f3d9fa,stroke:#9c36b5,stroke-width:2px
    style FEDB fill:#b2f2bb,stroke:#2f9e44,stroke-width:2px
```

### Quick Start

```bash
# 1. Install deps (uses uv)
uv sync --group dev

# 2. Run as a native desktop window
uv run python main.py

# 3. Or run as a local web server on :8550
IRONFLET_WEB=1 uv run python main.py

# 4. Or build the Android APK
flet build apk --target-platform android-arm64
```

---

**IronFlet** · Flet · Python

&copy; 2026 Alex Nolasco

</div>
