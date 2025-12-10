#!/usr/bin/env python3
"""
Retry failed downloads with longer timeouts.
"""

import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

EVENTS_FILE = Path(__file__).parent.parent / "events.json"
SUMMARY_FILE = Path(__file__).parent.parent / "download_summary.json"
OUTPUT_DIR = Path(__file__).parent.parent
SCROLL_PAUSE = 0.5
MAX_SCROLL_ATTEMPTS = 300

# INCREASED TIMEOUTS
PAGE_TIMEOUT = 60000  # 60 seconds (was 30)
CONTENT_WAIT = 12000  # 12 seconds (was 8)


def sanitize_filename(name: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*]', '', name)
    safe = re.sub(r'\s+', '-', safe)
    safe = re.sub(r'-+', '-', safe)
    safe = safe.strip('-')
    return safe[:80]


def format_transcript_as_markdown(event_name: str, date: str, transcript_entries: list) -> str:
    lines = [f"# {event_name}", f"**Date:** {date}", "", "---", ""]

    current_speaker = None
    for entry in transcript_entries:
        timestamp = entry.get('timestamp', '').strip()
        speaker = entry.get('speaker', '').strip()
        text = entry.get('text', '').strip()

        if not text:
            continue

        if speaker and speaker != current_speaker:
            current_speaker = speaker
            lines.append(f"### {speaker}")
            lines.append("")

        if timestamp:
            lines.append(f"**[{timestamp}]** {text}")
        else:
            lines.append(text)
        lines.append("")

    return '\n'.join(lines)


async def click_transcript_tab(page) -> bool:
    try:
        tab = await page.query_selector('button:has-text("Audio Transcript")')
        if tab:
            await tab.click()
            await page.wait_for_timeout(2000)
            return True
    except:
        pass
    return False


async def scrape_transcript(page) -> list:
    transcript_entries = []
    await page.wait_for_timeout(2000)
    await click_transcript_tab(page)

    seen_texts = set()
    scroll_count = 0
    no_new_count = 0
    last_count = 0

    while scroll_count < MAX_SCROLL_ATTEMPTS:
        entries = await page.evaluate('''() => {
            const results = [];
            const transcriptPanel = document.querySelector('.transcript-wrapper, [class*="transcript-list"]');

            if (!transcriptPanel) {
                const allLis = document.querySelectorAll('li');
                allLis.forEach(item => {
                    const text = item.textContent?.trim() || '';
                    const timestampMatch = text.match(/(\\d{2}:\\d{2}:\\d{2})/);
                    if (timestampMatch && text.length > 30) {
                        const timestamp = timestampMatch[1];
                        const beforeTimestamp = text.split(timestamp)[0].trim();
                        const parts = text.split(timestamp);
                        let transcriptText = parts.length > 2 ? parts[2].trim() : (parts[1] ? parts[1].trim() : '');
                        if (transcriptText.length > 5) {
                            results.push({ speaker: beforeTimestamp, timestamp: timestamp, text: transcriptText });
                        }
                    }
                });
                return results;
            }

            const items = transcriptPanel.querySelectorAll('li, [class*="item"], [class*="entry"]');
            items.forEach(item => {
                const text = item.textContent?.trim() || '';
                const timestampMatch = text.match(/(\\d{2}:\\d{2}:\\d{2})/);
                if (!timestampMatch) return;
                const timestamp = timestampMatch[1];
                const parts = text.split(timestamp);
                const speaker = parts[0] ? parts[0].trim() : '';
                let transcriptText = parts.length > 2 ? parts[2].trim() : (parts[1] ? parts[1].trim() : '');
                if (transcriptText.length > 5) {
                    results.push({ speaker: speaker, timestamp: timestamp, text: transcriptText });
                }
            });
            return results;
        }''')

        for entry in entries:
            text_key = entry.get('text', '')[:100]
            if text_key and text_key not in seen_texts:
                seen_texts.add(text_key)
                transcript_entries.append(entry)

        if len(transcript_entries) == last_count:
            no_new_count += 1
            if no_new_count >= 15:
                break
        else:
            no_new_count = 0
            last_count = len(transcript_entries)

        await page.evaluate('''() => {
            const containers = document.querySelectorAll('[class*="transcript"], [class*="Transcript"]');
            for (const container of containers) {
                if (container.scrollHeight > container.clientHeight) {
                    container.scrollTop += 500;
                    return;
                }
            }
            const ul = document.querySelector('ul');
            if (ul && ul.scrollHeight > ul.clientHeight) {
                ul.scrollTop += 500;
            }
        }''')

        await page.wait_for_timeout(int(SCROLL_PAUSE * 1000))
        scroll_count += 1

        if scroll_count % 50 == 0:
            print(f"    Scrolled {scroll_count}x, found {len(transcript_entries)} entries...")

    return transcript_entries


async def process_event(browser, event: dict, output_dir: Path) -> bool:
    event_name = event.get('event_name', 'Unknown Event')
    date = event.get('date', '')
    zoom_links = event.get('zoom_links', [])
    passcode = event.get('passcode', '')

    if not zoom_links:
        return False

    zoom_url = zoom_links[0]
    safe_name = sanitize_filename(event_name)
    filename = f"{date}-{safe_name}.md" if date else f"{safe_name}.md"
    output_path = output_dir / filename

    if output_path.exists():
        print(f"  Already exists: {filename}")
        return True

    context = await browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    )
    page = await context.new_page()
    await page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")

    try:
        print(f"  Navigating (timeout: {PAGE_TIMEOUT/1000}s)...")
        await page.goto(zoom_url, timeout=PAGE_TIMEOUT)
        await page.wait_for_load_state('networkidle', timeout=PAGE_TIMEOUT)

        # Check for error page
        title = await page.title()
        if 'Error' in title:
            body = await page.evaluate('() => document.body.innerText.substring(0, 200)')
            if 'does not exist' in body:
                print(f"  Recording expired/deleted")
                return False

        # Handle passcode
        if passcode:
            try:
                pwd_input = await page.wait_for_selector('input[type="password"]', timeout=5000)
                if pwd_input:
                    print(f"  Entering passcode...")
                    await pwd_input.fill(passcode)
                    submit = await page.query_selector('button[type="submit"], #passcode_btn')
                    if submit:
                        await submit.click()
                        await page.wait_for_load_state('networkidle', timeout=15000)
            except:
                pass

        print(f"  Waiting for content ({CONTENT_WAIT/1000}s)...")
        await page.wait_for_timeout(CONTENT_WAIT)

        # Check for video error
        video_error = await page.query_selector('text="The media could not be loaded"')
        if video_error:
            print(f"  Video failed to load")
            return False

        print(f"  Scraping transcript...")
        transcript_entries = await scrape_transcript(page)

        if not transcript_entries:
            print(f"  No transcript found")
            debug_dir = output_dir / "debug"
            debug_dir.mkdir(exist_ok=True)
            await page.screenshot(path=str(debug_dir / f"{safe_name}.png"))
            return False

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
    print("=" * 60)
    print("RETRY FAILED DOWNLOADS (with longer timeouts)")
    print("=" * 60)

    # Load events and failed list
    with open(EVENTS_FILE) as f:
        all_events = json.load(f)

    with open(SUMMARY_FILE) as f:
        summary = json.load(f)

    failed_names = summary['failed']

    # Get events that failed
    events_to_retry = []
    for event in all_events:
        name = event.get('event_name', '')
        if any(name.startswith(f[:40]) or f.startswith(name[:40]) for f in failed_names):
            events_to_retry.append(event)

    print(f"\nRetrying {len(events_to_retry)} failed events\n")

    successful = []
    failed = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            channel="chrome",
            args=['--disable-blink-features=AutomationControlled']
        )

        for i, event in enumerate(events_to_retry):
            event_name = event.get('event_name', 'Unknown')
            print(f"\n[{i+1}/{len(events_to_retry)}] {event_name[:50]}")
            print("-" * 60)

            success = await process_event(browser, event, OUTPUT_DIR)

            if success:
                successful.append(event_name)
            else:
                failed.append(event_name)

            await asyncio.sleep(2)

        await browser.close()

    print("\n" + "=" * 60)
    print("RETRY SUMMARY")
    print("=" * 60)
    print(f"Successful: {len(successful)}")
    print(f"Still failed: {len(failed)}")

    if successful:
        print("\nNewly downloaded:")
        for name in successful:
            print(f"  + {name[:60]}")

    # Update summary
    original_successful = summary.get('successful', [])
    summary['successful'] = original_successful + successful
    summary['failed'] = failed
    summary['retry_successful'] = len(successful)
    summary['retry_failed'] = len(failed)

    with open(SUMMARY_FILE, 'w') as f:
        json.dump(summary, f, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
