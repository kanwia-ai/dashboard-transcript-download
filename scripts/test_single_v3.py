#!/usr/bin/env python3
"""
Test script v3 - Use Chrome with user data to avoid codec issues.
"""

import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright


async def test_zoom_page():
    """Open Zoom recording using real Chrome browser profile."""

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
        # Launch with Chrome channel which has proper codecs
        browser = await p.chromium.launch(
            headless=False,
            channel="chrome",  # Use real Chrome instead of Chromium
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-web-security',
                '--allow-running-insecure-content',
            ]
        )

        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = await context.new_page()

        # Remove webdriver property
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

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
                print(f"   No passcode needed or error: {e}")

        # Wait longer for video to load
        print("\n3. Waiting for video player to load (10s)...")
        await page.wait_for_timeout(10000)

        # Check for video error
        video_error = await page.query_selector('text="The media could not be loaded"')
        if video_error:
            print("   ERROR: Video still cannot load")
        else:
            print("   Video appears to be loading")

        # Take screenshot
        screenshot_path = Path(__file__).parent.parent / "debug_screenshot_v3.png"
        await page.screenshot(path=str(screenshot_path), full_page=False)
        print(f"\n4. Screenshot saved to: {screenshot_path}")

        # Look for transcript tab
        print("\n5. Looking for Audio Transcript tab...")

        # Get all buttons and tabs
        buttons = await page.query_selector_all('button, [role="tab"]')
        print(f"   Found {len(buttons)} buttons/tabs")

        for btn in buttons[:20]:
            text = await btn.text_content()
            if text and 'transcript' in text.lower():
                print(f"   Found transcript button: {text}")
                await btn.click()
                await page.wait_for_timeout(2000)
                break

        # Look for transcript content
        print("\n6. Looking for transcript content...")

        # Search for any text that looks like transcript
        transcript_text = await page.evaluate('''() => {
            // Look for elements with substantial text content
            const allText = [];
            document.querySelectorAll('*').forEach(el => {
                const text = el.textContent?.trim();
                if (text && text.length > 50 && text.length < 500) {
                    // Check if it looks like transcript (has speaker names, timestamps)
                    if (text.match(/\\d{1,2}:\\d{2}/) || text.match(/Section|Hello|Welcome/i)) {
                        allText.push({
                            tag: el.tagName,
                            class: el.className?.substring(0, 50),
                            text: text.substring(0, 200)
                        });
                    }
                }
            });
            return allText.slice(0, 10);
        }''')

        if transcript_text:
            print(f"   Found {len(transcript_text)} potential transcript elements:")
            for item in transcript_text:
                print(f"     <{item['tag']}> {item['text'][:100]}...")
        else:
            print("   No transcript text found")

        # Keep browser open
        print("\n" + "=" * 50)
        print("Browser staying open for 2 minutes for manual inspection.")
        print("Please check if:")
        print("1. The video loads and plays")
        print("2. The Audio Transcript tab is visible")
        print("3. Clicking it shows transcript text")
        print("=" * 50)

        await page.wait_for_timeout(120000)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_zoom_page())
