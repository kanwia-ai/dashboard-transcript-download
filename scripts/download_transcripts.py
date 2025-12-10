#!/usr/bin/env python3
"""
Zoom Transcript Downloader for Marketing Events
Downloads transcripts from Zoom recording pages and saves them as Markdown files.

Usage:
    python download_transcripts.py              # Process all events
    python download_transcripts.py --test       # Process only first event (for testing)
    python download_transcripts.py --limit 5    # Process first 5 events
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# Configuration
EVENTS_FILE = Path(__file__).parent.parent / "events.json"
OUTPUT_DIR = Path(__file__).parent.parent
SCROLL_PAUSE = 0.5  # Seconds between scroll actions
MAX_SCROLL_ATTEMPTS = 300  # Maximum scroll iterations for long transcripts


def sanitize_filename(name: str) -> str:
    """Convert event name to safe filename."""
    safe = re.sub(r'[<>:"/\\|?*]', '', name)
    safe = re.sub(r'\s+', '-', safe)
    safe = re.sub(r'-+', '-', safe)
    safe = safe.strip('-')
    return safe[:80]


def format_transcript_as_markdown(event_name: str, date: str, transcript_entries: list) -> str:
    """Format transcript entries into Markdown."""
    lines = [
        f"# {event_name}",
        f"**Date:** {date}",
        "",
        "---",
        ""
    ]

    current_speaker = None
    for entry in transcript_entries:
        timestamp = entry.get('timestamp', '').strip()
        speaker = entry.get('speaker', '').strip()
        text = entry.get('text', '').strip()

        # Skip entries without text
        if not text:
            continue

        # Add speaker/timestamp header when speaker changes or first entry
        if speaker and speaker != current_speaker:
            current_speaker = speaker
            lines.append(f"### {speaker}")
            lines.append("")

        # Add timestamp and text
        if timestamp:
            lines.append(f"**[{timestamp}]** {text}")
        else:
            lines.append(text)
        lines.append("")

    return '\n'.join(lines)


async def enter_passcode(page, passcode: str) -> bool:
    """Enter passcode on Zoom recording page if required."""
    try:
        pwd_input = await page.wait_for_selector('input[type="password"]', timeout=5000)
        if pwd_input:
            print(f"    Entering passcode...")
            await pwd_input.fill(passcode)

            submit = await page.query_selector('button[type="submit"], #passcode_btn')
            if submit:
                await submit.click()
                await page.wait_for_load_state('networkidle', timeout=15000)
            return True
    except PlaywrightTimeout:
        print(f"    No passcode required")
        return True
    except Exception as e:
        print(f"    Passcode error: {e}")
        return False
    return True


async def click_transcript_tab(page) -> bool:
    """Click the Audio Transcript tab if not already active."""
    try:
        # Look for Audio Transcript button/tab
        tab = await page.query_selector('button:has-text("Audio Transcript")')
        if tab:
            await tab.click()
            await page.wait_for_timeout(2000)
            return True
    except Exception as e:
        print(f"    Note: Could not click transcript tab: {e}")
    return False


async def scrape_transcript(page) -> list:
    """Scrape the full transcript by scrolling through the transcript panel."""
    transcript_entries = []

    # Wait for transcript to be visible
    await page.wait_for_timeout(2000)

    # Click Audio Transcript tab
    await click_transcript_tab(page)

    seen_texts = set()
    scroll_count = 0
    no_new_count = 0
    last_count = 0

    while scroll_count < MAX_SCROLL_ATTEMPTS:
        # Extract transcript entries using JavaScript - more targeted approach
        entries = await page.evaluate('''() => {
            const results = [];

            // Look specifically for transcript list items within the transcript panel
            // The transcript wrapper contains the actual transcript entries
            const transcriptPanel = document.querySelector('.transcript-wrapper, [class*="transcript-list"], [class*="TranscriptList"]');

            if (!transcriptPanel) {
                // Fallback: look for li elements with timestamp pattern
                const allLis = document.querySelectorAll('li');
                allLis.forEach(item => {
                    const text = item.textContent?.trim() || '';
                    // Only include items that have a timestamp pattern (HH:MM:SS)
                    const timestampMatch = text.match(/(\\d{2}:\\d{2}:\\d{2})/);
                    if (timestampMatch && text.length > 30) {
                        const timestamp = timestampMatch[1];
                        // Extract speaker: text before timestamp
                        const beforeTimestamp = text.split(timestamp)[0].trim();
                        // Extract transcript text: after second occurrence of timestamp
                        const parts = text.split(timestamp);
                        let transcriptText = parts.length > 2 ? parts[2].trim() : (parts[1] ? parts[1].trim() : '');

                        if (transcriptText.length > 5) {
                            results.push({
                                speaker: beforeTimestamp,
                                timestamp: timestamp,
                                text: transcriptText
                            });
                        }
                    }
                });
                return results;
            }

            // If we found the transcript panel, look for entries within it
            const items = transcriptPanel.querySelectorAll('li, [class*="item"], [class*="entry"]');

            items.forEach(item => {
                const text = item.textContent?.trim() || '';

                // Must have timestamp to be a transcript entry
                const timestampMatch = text.match(/(\\d{2}:\\d{2}:\\d{2})/);
                if (!timestampMatch) return;

                const timestamp = timestampMatch[1];

                // Split by timestamp to get speaker and text
                const parts = text.split(timestamp);
                const speaker = parts[0] ? parts[0].trim() : '';
                // The text appears after the timestamp (which may appear twice)
                let transcriptText = parts.length > 2 ? parts[2].trim() : (parts[1] ? parts[1].trim() : '');

                if (transcriptText.length > 5) {
                    results.push({
                        speaker: speaker,
                        timestamp: timestamp,
                        text: transcriptText
                    });
                }
            });

            return results;
        }''')

        # Add new entries (dedupe by text)
        for entry in entries:
            text_key = entry.get('text', '')[:100]
            if text_key and text_key not in seen_texts:
                seen_texts.add(text_key)
                transcript_entries.append(entry)

        # Check progress
        if len(transcript_entries) == last_count:
            no_new_count += 1
            if no_new_count >= 15:
                print(f"    Finished scrolling (no new content)")
                break
        else:
            no_new_count = 0
            last_count = len(transcript_entries)

        # Scroll the transcript panel
        scrolled = await page.evaluate('''() => {
            // Find scrollable transcript container
            const containers = document.querySelectorAll('[class*="transcript"], [class*="Transcript"]');
            for (const container of containers) {
                if (container.scrollHeight > container.clientHeight) {
                    const before = container.scrollTop;
                    container.scrollTop += 500;
                    return container.scrollTop > before;
                }
            }

            // Fallback: try scrolling any ul element
            const ul = document.querySelector('ul');
            if (ul && ul.scrollHeight > ul.clientHeight) {
                const before = ul.scrollTop;
                ul.scrollTop += 500;
                return ul.scrollTop > before;
            }

            return false;
        }''')

        await page.wait_for_timeout(int(SCROLL_PAUSE * 1000))
        scroll_count += 1

        if scroll_count % 30 == 0:
            print(f"    Scrolled {scroll_count}x, found {len(transcript_entries)} entries...")

    print(f"    Total entries: {len(transcript_entries)}")
    return transcript_entries


async def process_event(browser, event: dict, output_dir: Path) -> bool:
    """Process a single event."""
    event_name = event.get('event_name', 'Unknown Event')
    date = event.get('date', '')
    zoom_links = event.get('zoom_links', [])
    passcode = event.get('passcode', '')

    if not zoom_links:
        print(f"  No Zoom links")
        return False

    zoom_url = zoom_links[0]

    # Create filename
    safe_name = sanitize_filename(event_name)
    filename = f"{date}-{safe_name}.md" if date else f"{safe_name}.md"
    output_path = output_dir / filename

    # Skip if already exists
    if output_path.exists():
        print(f"  Already exists: {filename}")
        return True

    context = await browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    page = await context.new_page()

    # Hide automation
    await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    """)

    try:
        print(f"  Navigating to Zoom...")
        await page.goto(zoom_url, timeout=30000)
        await page.wait_for_load_state('networkidle', timeout=30000)

        # Handle passcode
        if passcode:
            await enter_passcode(page, passcode)

        # Wait for video/transcript to load
        print(f"  Waiting for content to load...")
        await page.wait_for_timeout(8000)

        # Check for video error
        video_error = await page.query_selector('text="The media could not be loaded"')
        if video_error:
            print(f"  ERROR: Video failed to load")
            await context.close()
            return False

        # Scrape transcript
        print(f"  Scraping transcript...")
        transcript_entries = await scrape_transcript(page)

        if not transcript_entries:
            print(f"  No transcript found")
            # Save debug info
            debug_dir = output_dir / "debug"
            debug_dir.mkdir(exist_ok=True)
            await page.screenshot(path=str(debug_dir / f"{safe_name}.png"))
            await context.close()
            return False

        # Format and save
        markdown = format_transcript_as_markdown(event_name, date, transcript_entries)
        output_path.write_text(markdown)
        print(f"  Saved: {filename} ({len(transcript_entries)} entries)")

        return True

    except Exception as e:
        print(f"  Error: {e}")
        return False
    finally:
        await context.close()


async def main():
    parser = argparse.ArgumentParser(description='Download Zoom transcripts')
    parser.add_argument('--test', action='store_true', help='Process only first event')
    parser.add_argument('--limit', type=int, help='Limit number of events to process')
    args = parser.parse_args()

    print("=" * 60)
    print("Zoom Transcript Downloader for Marketing Events")
    print("=" * 60)

    if not EVENTS_FILE.exists():
        print(f"Error: Events file not found: {EVENTS_FILE}")
        sys.exit(1)

    with open(EVENTS_FILE) as f:
        events = json.load(f)

    # Apply limits
    if args.test:
        events = events[:1]
        print("TEST MODE: Processing only first event")
    elif args.limit:
        events = events[:args.limit]
        print(f"Processing first {args.limit} events")

    print(f"\nLoaded {len(events)} events to process\n")

    successful = []
    failed = []

    async with async_playwright() as p:
        # Use Chrome for proper video codec support
        browser = await p.chromium.launch(
            headless=False,
            channel="chrome",
            args=['--disable-blink-features=AutomationControlled']
        )

        for i, event in enumerate(events):
            event_name = event.get('event_name', 'Unknown')
            print(f"\n[{i+1}/{len(events)}] {event_name[:50]}")
            print("-" * 60)

            success = await process_event(browser, event, OUTPUT_DIR)

            if success:
                successful.append(event_name)
            else:
                failed.append(event_name)

            # Small delay between events
            if i < len(events) - 1:
                await asyncio.sleep(2)

        await browser.close()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")

    if failed:
        print("\nFailed events:")
        for name in failed:
            print(f"  - {name[:60]}")

    # Save summary
    summary_path = OUTPUT_DIR / "download_summary.json"
    with open(summary_path, 'w') as f:
        json.dump({
            'successful': successful,
            'failed': failed,
            'total': len(events)
        }, f, indent=2)
    print(f"\nSummary saved to: {summary_path}")


if __name__ == "__main__":
    asyncio.run(main())
