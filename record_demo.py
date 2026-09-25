import asyncio
import os
import shutil
import time
from playwright.async_api import async_playwright

ARTIFACT_DIR = "/config/.gemini/antigravity/brain/3f935092-9cc4-42a5-ac44-8675f97afd6c"
SCRATCH_RECORDING_DIR = os.path.join(ARTIFACT_DIR, "scratch", "demo_recording")
FINAL_VIDEO_PATH = os.path.join(ARTIFACT_DIR, "recipe_assistant_demo.webm")

async def record_demo():
    os.makedirs(SCRATCH_RECORDING_DIR, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            record_video_dir=SCRATCH_RECORDING_DIR,
            record_video_size={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        print("Navigating to http://localhost:8080...")
        await page.goto("http://localhost:8080", wait_until="networkidle")
        await page.wait_for_timeout(2000)

        # Prompt 1: Find a quick pasta recipe
        prompt1 = "Find a quick pasta recipe for a 15-minute weeknight dinner"
        print(f"Sending Prompt 1: {prompt1}")
        input_selector = "#input"
        await page.click(input_selector)
        await page.type(input_selector, prompt1, delay=40)
        await page.wait_for_timeout(500)
        await page.click("button[type='submit']")

        # Wait for agent response
        print("Waiting for response to Prompt 1...")
        await page.wait_for_selector(".msg.agent", timeout=30000)
        await page.wait_for_timeout(6000)

        # Prompt 2: Scale recipe & generate visual
        prompt2 = "Scale Creamy Tuscan Pasta to 8 servings and generate a realistic visual image"
        print(f"Sending Prompt 2: {prompt2}")
        await page.click(input_selector)
        await page.type(input_selector, prompt2, delay=35)
        await page.wait_for_timeout(500)
        await page.click("button[type='submit']")

        # Wait for second agent response
        print("Waiting for response to Prompt 2 (tool call + image generation)...")
        await page.wait_for_timeout(10000)
        # Give enough time for image generation and card rendering
        await page.wait_for_timeout(8000)

        video = page.video
        await context.close()
        await browser.close()

        if video:
            video_path = await video.path()
            print(f"Recorded video saved to: {video_path}")
            shutil.copy(video_path, FINAL_VIDEO_PATH)
            print(f"Copied final video to artifact location: {FINAL_VIDEO_PATH}")

if __name__ == "__main__":
    asyncio.run(record_demo())
