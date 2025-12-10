#!/usr/bin/env python3
"""
Test script v2 - waits for transcript content to actually load.
"""

import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright


async def test_zoom_page():
    """Open Zoom recording and wait for transcript to load."""

    events_file = Path(__file__).parent.parent / "events.json"
    with open(events_file) as f:
        events = json.load(f)

    # Find test event with passcode
    test_event = None
    for e in events:
        if "Driving" in e.get('event_name', ''):
            test_event = e
            break

    if not test_event:
        test_event = events[0]

    print(f"Testing with: {test_event['event_name']}")
    print(f"URL: {test_event['zoom_links'][0]}")
    print(f"Passcode: {test_event.get('passcode', 'None')}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # Navigate
        print("\n1. Navigating to Zoom...")
        await page.goto(test_event['zoom_links'][0], timeout=30000)
        await page.wait_for_load_state('networkidle')

        # Handle passcode
        passcode = test_event.get('passcode', '')
        if passcode:
            print(f"\n2. Looking for passcode input...")
            try:
                pwd_input = await page.wait_for_selector('input[type="password"]', timeout=5000)
                if pwd_input:
                    print(f"   Entering passcode: {passcode}")
                    await pwd_input.fill(passcode)

                    submit = await page.query_selector('button[type="submit"], #passcode_btn')
                    if submit:
                        await submit.click()
                        await page.wait_for_load_state('networkidle', timeout=15000)
                        print("   Passcode submitted")
            except Exception as e:
                print(f"   Passcode handling: {e}")

        # Wait for video player to load
        print("\n3. Waiting for video player...")
        await page.wait_for_timeout(5000)

        # Look for and click Audio Transcript tab
        print("\n4. Looking for Audio Transcript tab...")

        # Try multiple selectors for the transcript tab
        tab_selectors = [
            'button:has-text("Audio Transcript")',
            '[role="tab"]:has-text("Audio Transcript")',
            '[data-testid="audio-transcript-tab"]',
            '.transcript-tab',
            'text="Audio Transcript"',
        ]

        tab_clicked = False
        for selector in tab_selectors:
            try:
                tab = await page.wait_for_selector(selector, timeout=3000)
                if tab:
                    print(f"   Found tab with selector: {selector}")
                    await tab.click()
                    tab_clicked = True
                    break
            except:
                continue

        if not tab_clicked:
            print("   Could not find Audio Transcript tab - checking if transcript is already visible")

        # Wait for transcript content to load
        print("\n5. Waiting for transcript content...")
        await page.wait_for_timeout(3000)

        # Try to find transcript entries
        transcript_selectors = [
            '[class*="transcript-sentence"]',
            '[class*="transcript-item"]',
            '[class*="TranscriptItem"]',
            '[class*="caption"]',
            '[class*="vtt-item"]',
            '.transcript-wrapper > *',
        ]

        for selector in transcript_selectors:
            try:
                elements = await page.query_selector_all(selector)
                if elements and len(elements) > 0:
                    print(f"   Found {len(elements)} elements with: {selector}")

                    # Get text from first few elements
                    for i, el in enumerate(elements[:5]):
                        text = await el.text_content()
                        print(f"     [{i}]: {text[:100] if text else 'empty'}")
            except Exception as e:
                pass

        # Get current page HTML around transcript area
        print("\n6. Analyzing transcript area...")
        transcript_html = await page.evaluate('''() => {
            const wrapper = document.querySelector('.transcript-wrapper');
            if (wrapper) {
                return {
                    html: wrapper.innerHTML.substring(0, 2000),
                    childCount: wrapper.children.length,
                    classes: Array.from(wrapper.classList)
                };
            }
            return null;
        }''')

        if transcript_html:
            print(f"   transcript-wrapper children: {transcript_html['childCount']}")
            print(f"   HTML preview: {transcript_html['html'][:500]}...")
        else:
            print("   transcript-wrapper not found or empty")

        # Take a screenshot for inspection
        screenshot_path = Path(__file__).parent.parent / "debug_screenshot.png"
        await page.screenshot(path=str(screenshot_path), full_page=False)
        print(f"\n7. Screenshot saved to: {screenshot_path}")

        # Save HTML
        html = await page.content()
        debug_path = Path(__file__).parent.parent / "debug_page_v2.html"
        debug_path.write_text(html)
        print(f"   HTML saved to: {debug_path}")

        # Keep browser open
        print("\n" + "=" * 50)
        print("Browser open for 90 seconds - manually inspect:")
        print("1. Is the video playing?")
        print("2. Is there an 'Audio Transcript' tab on the right?")
        print("3. Does clicking it show transcript text?")
        print("=" * 50)

        await page.wait_for_timeout(90000)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_zoom_page())
