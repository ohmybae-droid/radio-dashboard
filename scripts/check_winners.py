"""
디버그 버전: 페이지의 실제 HTML을 저장해서 KBS가 뭘 보내는지 확인.
"""
import asyncio
import json
import re
import os
from datetime import datetime, timedelta, timezone
from playwright.async_api import async_playwright

KST = timezone(timedelta(hours=9))

PROGRAMS = [
    {
        "name": "조정식의 FM대행진",
        "slug": "sikfm",
        "url": "https://program.kbs.co.kr/2fm/radio/sikfm/pc/board.html?smenu=adca27&bbs_loc=R2023-0192-03-656260,list,none,1,0",
    },
    {
        "name": "한해의 키스더라디오",
        "slug": "hanhaekiss",
        "url": "https://program.kbs.co.kr/2fm/radio/hanhaekiss/pc/board.html?smenu=906dc8&bbs_loc=R2025-0082-03-722746,list,none,1,0",
    },
]


def match_line(line):
    reasons = []
    strong_count = 0
    weak_count = 0
    if "배가영" in line:
        reasons.append('풀네임 "배가영"')
        strong_count += 1
    if re.search(r"-\s*0304(?!\d)", line):
        reasons.append('전화번호 뒤 4자리 "0304"')
        strong_count += 1
    lower = line.lower()
    if "baby_b" in lower:
        reasons.append('ID "baby_b***"')
        strong_count += 1
    elif "baby_" in lower:
        reasons.append('ID "baby_"')
        weak_count += 1
    if "배가영" not in line:
        for p in [r"배\s*[*·\-]\s*영", r"배\s*가\s*[*·\-]", r"[*·\-]\s*가\s*영"]:
            if re.search(p, line):
                reasons.append("이름 마스킹 패턴")
                weak_count += 1
                break
    if strong_count >= 1: return ("high", reasons)
    if weak_count >= 2: return ("medium", reasons)
    if weak_count >= 1: return ("low", reasons)
    return (None, [])


async def check_program(browser, program):
    result = {
        "program": program["name"],
        "url": program["url"],
        "success": False,
        "matches": [],
        "error": None,
        "page_length": 0,
        "html_length": 0,
        "page_text_sample": "",
        "network_log": [],
    }
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        locale="ko-KR",
        viewport={"width": 1280, "height": 900},
        extra_http_headers={
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    page = await context.new_page()
    
    # 네트워크 활동 추적
    network_log = []
    def on_response(response):
        url = response.url
        # KBS API 호출만 필터링
        if 'kbs.co.kr' in url and ('api' in url.lower() or '.json' in url.lower() or 'bbs' in url.lower()):
            network_log.append(f"[{response.status}] {url[:150]}")
    page.on("response", on_response)
    
    try:
        print(f"→ Loading: {program['name']}")
        response = await page.goto(program["url"], wait_until="domcontentloaded", timeout=60000)
        print(f"  HTTP status: {response.status if response else 'N/A'}")
        
        # 20초 대기 (AngularJS 로딩)
        for i in range(10):
            await page.wait_for_timeout(2000)
            text = await page.inner_text("body")
            print(f"  [{(i+1)*2}s] text length: {len(text)}")
            if len(text) > 2000:
                break
        
        text = await page.inner_text("body")
        html = await page.content()
        result["page_length"] = len(text)
        result["html_length"] = len(html)
        result["page_text_sample"] = text[:1500]
        result["network_log"] = network_log[:20]
        
        # HTML 스냅샷 저장 (디버깅용)
        os.makedirs("data/debug", exist_ok=True)
        with open(f"data/debug/{program['slug']}.html", "w", encoding="utf-8") as f:
            f.write(html)
        with open(f"data/debug/{program['slug']}.txt", "w", encoding="utf-8") as f:
            f.write(text)
        
        # 스크린샷도 저장
        await page.screenshot(path=f"data/debug/{program['slug']}.png", full_page=True)
        
        for line in text.split("\n"):
            line = line.strip()
            if not line or len(line) > 500:
                continue
            conf, reasons = match_line(line)
            if conf:
                result["matches"].append({"confidence": conf, "line": line[:200], "reasons": reasons})
        
        result["success"] = True
        print(f"  ✓ Got {len(text)} chars text, {len(html)} chars HTML, {len(result['matches'])} matches")
        print(f"  Network calls to KBS APIs: {len(network_log)}")
        for n in network_log[:5]:
            print(f"    {n}")
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        print(f"  ✗ Error: {result['error']}")
    finally:
        await page.close()
        await context.close()
    return result


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        results = []
        for program in PROGRAMS:
            r = await check_program(browser, program)
            results.append(r)
        await browser.close()

    output = {
        "checked_at": datetime.now(KST).isoformat(),
        "programs": results,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/latest-check.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n=== Summary ===")
    for r in results:
        status = "✓" if r["success"] else "✗"
        m = len(r["matches"]) if r["success"] else 0
        print(f"{status} {r['program']}: {m} matches (text: {r['page_length']}, html: {r['html_length']})")


if __name__ == "__main__":
    asyncio.run(main())
