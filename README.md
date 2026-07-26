# MUSIC TAGGER // SYSTEM GRID

A sleek, TRON-themed containerized web application built with Flask and Bootstrap designed to scan, automatically query metadata via MusicBrainz, clean up tags, and conditionally restructure your music library.

---

## Features

* **TRON-Themed Glassmorphism UI**: Immersive dark-mode grid aesthetic featuring animated perimeter lightcycle border tracers, custom styling, and a live diagnostic terminal console.
* **Intelligent Metadata Fetching**: Automatically queries MusicBrainz to resolve accurate track numbers, studio album titles, release years, and clean track names.
* **Smart Organization Bypass**: Automatically detects and bypasses files that are already properly tagged and structured.
* **Interactive Directory Explorer**: Built-in modal file system browser to easily navigate and select your target container storage paths.
* **Multi-Phase Review & Execution Workflow**:
* **Phase 1**: Review and edit extracted metadata parameters across a batch table.
* **Phase 2**: Preview automatic directory restructuring and file renaming operations.
* **Phase 3**: Final command manifest verification before committing batch writes.


* **Robust Exception Handling**: Surfaces unparseable or failed files for easy review.

---

## Tech Stack

* **Backend**: Python, Flask, MusicBrainzNGS, Mutagen (`EasyID3`, `MP3`)
* **Frontend**: HTML5, Bootstrap 5, Custom CSS3 Grid & Animations
* **Environment**: Docker & Docker Compose

---

## Installation & Deployment

1. Clone the repository to your local machine or server.
2. Ensure you have Docker and Docker Compose installed.
3. Build and launch the container:

```bash
docker compose up --build -d

```

4. Access the application in your web browser at:

```text
http://localhost:5000

```

---

## Usage Guide

1. **Target Repository**: Enter your container music directory path (default is `/music`) or click **QUERY DISK...** to use the interactive directory sector explorer modal.
2. **Initialize Scan**: Click **INITIALIZE METADATA EXTRACTION & STREAM REVIEW** to begin scanning files and watching real-time logs in the terminal console.
3. **Phase 1 (Metadata)**: Verify and tweak artists, albums, years, track numbers, and titles. Uncheck any items you want to skip.
4. **Phase 2 (Restructuring)**: Preview proposed folder paths (`Artist / (Year) Album / Track - Title.ext`) and select/deselect structural moves.
5. **Phase 3 (Final Execution)**: Confirm your final manifest queue and click **EXECUTE BATCH WRITES // COMMIT** to apply ID3 tags and relocate files.