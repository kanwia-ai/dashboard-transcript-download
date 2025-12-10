# Dashboard Transcript Download

Automated Zoom transcript downloader that extracts transcripts from Zoom recording pages and saves them as formatted Markdown files.

## What It Does

- Reads event data from a Google Sheets export (event names, dates, Zoom links, passcodes)
- Opens Zoom recording pages using Playwright browser automation
- Handles passcode-protected recordings automatically
- Scrolls through transcript panels to capture full transcripts
- Saves transcripts as Markdown files with speaker names and timestamps

## Tech Stack

- **Python 3** with async/await
- **Playwright** for browser automation (uses Chrome for video codec support)
- **pandas** for Excel/CSV data processing

## Scripts

| Script | Description |
|--------|-------------|
| `scripts/download_transcripts.py` | Main batch downloader - processes all events from events.json |
| `scripts/retry_failed.py` | Retry script with longer timeouts (60s vs 30s) for failed downloads |

## Output Format

Transcripts are saved as `YYYY-MM-DD-Event-Name.md` with this structure:

```markdown
# Event Name
**Date:** 2025-01-15

---

### Speaker Name

**[00:01:23]** Transcript text here...

**[00:01:45]** More transcript text...
```

## Usage

```bash
# Process all events
python scripts/download_transcripts.py

# Process only first event (test mode)
python scripts/download_transcripts.py --test

# Process first N events
python scripts/download_transcripts.py --limit 5

# Retry failed downloads with longer timeouts
python scripts/retry_failed.py
```

## Requirements

```bash
pip install playwright pandas openpyxl
playwright install chromium
```

## Notes

- Uses Chrome channel (not Chromium) for proper video codec support
- Some recordings may fail if they've been deleted from Zoom or have no transcript
- Debug screenshots are saved for failed downloads to help troubleshoot

---

Generated with [Claude Code](https://claude.com/claude-code)
