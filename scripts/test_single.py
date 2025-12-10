#!/usr/bin/env python3
"""
Test script to explore Zoom transcript page structure.
Run this first to understand the DOM before full automation.
"""

import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright


async def test_zoom_page():
    """Open a single Zoom recording and explore the page structure."""

    # Load one event with passcode for testing
    events_file = Path(__file__).parent.parent / "events.json"
    with open(events_file) as f:
        events = json.load(f)

    # Find "Driving & Measuring Rapid AI Adoption" which has a passcode
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
        print("\nNavigating to Zoom...")
        await page.goto(test_event['zoom_links'][0], timeout=30000)
        await page.wait_for_load_state('networkidle')

        # Check for passcode prompt
        passcode = test_event.get('passcode', '')
        if passcode:
            print(f"\nLooking for passcode input...")
            try:
                # Look for password input
                pwd_input = await page.wait_for_selector(
                    'input[type="password"]',
                    timeout=5000
                )
                if pwd_input:
                    print(f"Found password input, entering: {passcode}")
                    await pwd_input.fill(passcode)

                    # Find and click submit
                    submit = await page.query_selector('button[type="submit"], #passcode_btn')
                    if submit:
                        await submit.click()
                        await page.wait_for_load_state('networkidle', timeout=15000)
                        print("Submitted passcode")
            except Exception as e:
                print(f"Passcode handling: {e}")

        # Wait for transcript to load
        await page.wait_for_timeout(3000)

        # Click Audio Transcript tab
        print("\nLooking for Audio Transcript tab...")
        try:
            tab = await page.query_selector('button:has-text("Audio Transcript")')
            if tab:
                print("Clicking Audio Transcript tab...")
                await tab.click()
                await page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Tab click: {e}")

        # Now let's inspect the page structure
        print("\n" + "=" * 50)
        print("PAGE STRUCTURE ANALYSIS")
        print("=" * 50)

        # Get all elements that might contain transcript
        analysis = await page.evaluate('''() => {
            const results = {
                transcript_classes: [],
                potential_containers: [],
                text_samples: []
            };

            // Find elements with 'transcript' in class name
            document.querySelectorAll('*').forEach(el => {
                const className = el.className;
                if (typeof className === 'string' && className.toLowerCase().includes('transcript')) {
                    results.transcript_classes.push({
                        tag: el.tagName,
                        class: className.substring(0, 100),
                        childCount: el.children.length
                    });
                }
            });

            // Look for speaker/timestamp patterns
            document.querySelectorAll('[class*="speaker"], [class*="time"], [class*="caption"]').forEach(el => {
                const text = el.textContent?.trim().substring(0, 100);
                if (text) {
                    results.potential_containers.push({
                        tag: el.tagName,
                        class: el.className?.substring(0, 80),
                        text: text
                    });
                }
            });

            // Get some text samples from the transcript area
            const transcriptArea = document.querySelector('[class*="transcript"]');
            if (transcriptArea) {
                const children = transcriptArea.querySelectorAll('*');
                for (let i = 0; i < Math.min(20, children.length); i++) {
                    const text = children[i].textContent?.trim();
                    if (text && text.length > 5 && text.length < 200) {
                        results.text_samples.push({
                            tag: children[i].tagName,
                            class: children[i].className?.substring(0, 50),
                            text: text
                        });
                    }
                }
            }

            return results;
        }''')

        print("\nElements with 'transcript' in class:")
        for item in analysis.get('transcript_classes', [])[:10]:
            print(f"  <{item['tag']}> class='{item['class']}' children={item['childCount']}")

        print("\nPotential speaker/time containers:")
        for item in analysis.get('potential_containers', [])[:10]:
            print(f"  <{item['tag']}> class='{item['class']}'")
            print(f"    text: {item['text'][:80]}")

        print("\nText samples from transcript area:")
        for item in analysis.get('text_samples', [])[:10]:
            print(f"  <{item['tag']}> {item['text'][:100]}")

        # Save full page HTML for analysis
        html = await page.content()
        debug_path = Path(__file__).parent.parent / "debug_page.html"
        debug_path.write_text(html)
        print(f"\nSaved full HTML to: {debug_path}")

        # Keep browser open for manual inspection
        print("\n" + "=" * 50)
        print("Browser will stay open for 60 seconds for manual inspection.")
        print("Check the page structure and transcript panel.")
        print("=" * 50)

        await page.wait_for_timeout(60000)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_zoom_page())
