"""Generate a 1200x630 social preview image for Call-Pilot."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

CALL_CENTER_DIR = Path(__file__).resolve().parent.parent
OUTPUT = CALL_CENTER_DIR / "static" / "og-cover.png"

HTML = """
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<style>
  * { box-sizing: border-box; }
  body { margin: 0; }
  .cover {
    width: 1200px; height: 630px; padding: 64px 68px;
    display: flex; flex-direction: column; justify-content: space-between;
    background:
      radial-gradient(90% 120% at 8% 0%, #16243f 0%, #0b1220 58%, #071019 100%);
    color: #f8fafc;
    font-family: "Segoe UI", "Arial", sans-serif;
    position: relative; overflow: hidden;
  }
  .glow-a {
    position: absolute; width: 480px; height: 480px; border-radius: 50%;
    background: rgba(20, 184, 166, .28); filter: blur(90px); top: -180px; right: 40px;
  }
  .glow-b {
    position: absolute; width: 360px; height: 360px; border-radius: 50%;
    background: rgba(37, 99, 235, .22); filter: blur(100px); bottom: -160px; left: 80px;
  }
  .top, .middle, .bottom { position: relative; z-index: 1; }
  .brand { display: flex; align-items: center; gap: 16px; font-size: 28px; font-weight: 800; letter-spacing: -.02em; }
  .brand svg { width: 60px; height: 60px; }
  .eyebrow { color: #5eead4; font-size: 17px; font-weight: 800; letter-spacing: .16em; text-transform: uppercase; }
  h1 { margin: 18px 0 0; font-size: 56px; line-height: 1.08; letter-spacing: -.045em; font-weight: 800; max-width: 1020px; }
  h1 span { color: #5eead4; }
  .bottom {
    display: flex; align-items: center; justify-content: space-between; gap: 30px;
    border-top: 1px solid rgba(148, 163, 184, .25); padding-top: 22px;
    font-size: 19px; color: #cbd5e1;
  }
  .bottom strong { color: #f8fafc; }
</style>
</head>
<body>
<div class="cover">
  <div class="glow-a"></div>
  <div class="glow-b"></div>
  <div class="top">
    <div class="brand">
      <svg viewBox="0 0 64 64" aria-hidden="true">
        <rect width="64" height="64" rx="16" fill="#0b1220"/>
        <path d="M20 18c0-2 2-3 4-2l4 7c1 2 0 3-1 4l-2 2c2 5 6 9 11 11l2-2c1-1 3-2 4-1l7 4c2 1 2 3 1 4l-2 3c-1 2-4 3-6 2C28 44 20 36 18 24c-1-2 0-4 2-4z" fill="#14b8a6"/>
        <path d="M40 20c4 2 6 5 6 9" stroke="#fbbf24" stroke-width="3" stroke-linecap="round" fill="none"/>
        <path d="M42 13c6 3 10 9 10 16" stroke="#fbbf24" stroke-width="3" stroke-linecap="round" fill="none" opacity=".65"/>
      </svg>
      <span>Call-Pilot</span>
    </div>
  </div>
  <div class="middle">
    <div class="eyebrow">AI-постобработка и QA звонков</div>
    <h1>AI заполняет карточку.<br><span>Оператор подтверждает.</span><br>QA проверяет каждый звонок.</h1>
  </div>
  <div class="bottom">
    <span><strong>100% QA</strong> · HITL · CRM</span>
    <span><strong>call-pilot.ru</strong> · +7 962 609-00-01</span>
  </div>
</div>
</body>
</html>
"""


def main() -> int:
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
        except Exception:
            browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1200, "height": 630},
            device_scale_factor=1,
        )
        page.set_content(HTML, wait_until="load")
        page.wait_for_timeout(300)
        page.screenshot(path=str(OUTPUT), clip={"x": 0, "y": 0, "width": 1200, "height": 630})
        browser.close()
    print(f"OG image: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
