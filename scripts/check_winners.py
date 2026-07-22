"""
KBS 라디오 게시판에서 어제 당첨자 목록을 확인하는 스크립트.
GitHub Actions에서 매일 실행됨. 결과는 data/latest-check.json에 저장.
v2: AngularJS 렌더링 대기 개선
"""
import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from playwright.async_api import async_playwright

KST = timezone(timedelta(hours=9))

PROGRAMS = [
    {
        "name": "조정식의 FM대행진",
        "url": "https://program.kbs.co.kr/2fm/radio/sikfm/pc/board.html?smenu=adca27&bbs_loc=R2023-0192-03-656260,list,none,1,0",
    },
    {
        "name": "한해의 키스더라디오",
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
        masked_patterns = [
            r"배\s*[*·\-]\s*영",
            r"배\s*가\s*[*·\-]",
            r"[*·\-]\s*가\s*영",
        ]
        for p in masked_patterns:
            if re.search(p, line):
                reasons.append("이름 마스킹 패턴")
                weak_count += 1
                break

    if strong_count >= 1:
        return ("high", reasons)
    if weak_count >= 2:
        return ("medium", reasons)
    if weak_count >= 1:
        return ("low", reasons)
    return (None, [])


async def wait_for_content(page, min_length=2000, max_wait_seconds=45):
    """페이지의 innerText가 충분한 길이가 될 때까지 대기."""
    start = asyncio.get_event_loop().time()
    last_length = 0
    stable_count = 0
    
    while True:
        elapsed = asyncio.get_event_loop().time() - start
        if elapsed > max_wait_seconds:
            print(f"    [wait] Timeout after {max_wait_seconds}s")
            return
        
        try:
            text = await page.inner_text("body")
            length = len(text)
        except:
            length = 0
        
        print(f"    [wait] {elapsed:.1f}s - text length: {length}")
        
        if length >= min_length and length == last_length:
            stable_count += 1
            if stable_count >= 2:
                print(f"    [wait] Content stable at {length} chars")
                return
        else:
            stable_count = 0
        
        last_length = length
        await page.wait_for_timeout(2000)


async def check_program(browser, program):
    result = {
        "program": program["name"],
        "url": program["url"],
        "success": False,
        "matches": [],
        "error": None,
        "page_length": 0,
        "page_text_sample": "",
    }
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        locale="ko-KR",
        viewport={"width": 1280, "height": 900},
    )
    page = await context.new_page()
    try:
        print(f"→ Loading: {program['name']}")
        await page.goto(program["url"], wait_until="domcontentloaded", timeout=60000)
        
        # AngularJS 렌더링 대기
        await wait_for_content(page, min_length=2000, max_wait_seconds=45)
        
        text = await page.inner_text("body")
        result["page_length"] = len(text)
        result["page_text_sample"] = text[:800]

        for line in text.split("\n"):
            line = line.strip()
            if not line or len(line) > 500:
                continue
            conf, reasons = match_line(line)
            if conf:
                result["matches"].append(
                    {"confidence": conf, "line": line[:200], "reasons": reasons}
                )

        result["success"] = True
        print(f"  ✓ Got {len(text)} chars, {len(result['matches'])} matches")
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

    import os
    os.makedirs("data", exist_ok=True)
    with open("data/latest-check.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n=== Summary ===")
    for r in results:
        status = "✓" if r["success"] else "✗"
        m = len(r["matches"]) if r["success"] else 0
        print(f"{status} {r['program']}: {m} matches (page: {r['page_length']} chars)")


if __name__ == "__main__":
    asyncio.run(main())
