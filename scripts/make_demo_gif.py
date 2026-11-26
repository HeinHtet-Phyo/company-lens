"""Record the UI with Playwright and build docs/demo.gif (needs a running server and live keys)."""

import io
import sys
import time

from PIL import Image
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
QUERY = sys.argv[2] if len(sys.argv) > 2 else "Greggs plc"


def main() -> None:
    """Type a query, capture frames while the report streams, write the GIF."""
    frames: list[Image.Image] = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 900, "height": 700})
        pg.goto(BASE)

        def snap() -> None:
            img = Image.open(io.BytesIO(pg.screenshot())).convert("RGB")
            frames.append(img.resize((720, 560)))

        snap()
        pg.fill("#q", QUERY)
        snap()
        pg.click("#go")
        t0 = time.time()
        while time.time() - t0 < 90:
            time.sleep(1.2)
            snap()
            if pg.locator(".badge").count() or pg.locator(".err").count():
                break
        pg.mouse.wheel(0, 500)
        time.sleep(0.5)
        snap()
        snap()
        b.close()
    pal = [f.quantize(colors=64, method=Image.Quantize.MEDIANCUT) for f in frames]
    pal[0].save(
        "docs/demo.gif",
        save_all=True,
        append_images=pal[1:],
        duration=[900] * (len(pal) - 1) + [2500],
        loop=0,
        optimize=True,
    )
    print(len(frames), "frames")


main()
