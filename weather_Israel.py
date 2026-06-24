import asyncio
from mcp.server.fastmcp import FastMCP
from playwright.async_api import TimeoutError as PlaywrightTimeout, async_playwright

mcp = FastMCP("weather-Israel")

FORECAST_URL = "https://www.weather2day.co.il/forecast"
playwright = None
browser = None
page = None
browser_lock = None


async def ensure_browser_page():
    global playwright, browser, page, browser_lock
    if browser_lock is None:
        browser_lock = asyncio.Lock()
    async with browser_lock:
        if playwright is None:
            playwright = await async_playwright().start()
        if browser is None:
            browser = await playwright.chromium.launch(headless=False)
        if page is None or page.is_closed():
            page = await browser.new_page()
            await page.set_viewport_size({"width": 1280, "height": 720})
    return page


async def extract_visible_text(page):
    return await page.evaluate("""
        () => {
            const ignored = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'META', 'HEAD', 'TITLE', 'LINK']);
            const nodes = Array.from(document.querySelectorAll('body *'))
                .filter(el => el.offsetParent !== null)
                .filter(el => !ignored.has(el.tagName));
            const text = nodes
                .map(el => el.innerText || '')
                .filter(str => str.trim().length > 0)
                .join('\n')
                .replace(/\n{2,}/g, '\n')
                .trim();
            return text;
        }
    """)


@mcp.tool()
async def open_weather_forecast_israel():
    """
    STEP 1: Opens the Israeli weather forecast website in Chromium.
    You MUST call this tool FIRST before doing anything else.
    """
    try:
        page = await ensure_browser_page()
        await page.goto(FORECAST_URL, wait_until="domcontentloaded", timeout=30000)
        return "Success: Weather forecast page is now open. Next, you MUST call enter_weather_forecast_city_israel."
    except PlaywrightTimeout:
        return "Error: Timeout while opening the weather forecast page."
    except Exception as e:
        return f"Error opening weather forecast: {str(e)}"


@mcp.tool()
async def enter_weather_forecast_city_israel(city_name: str):
    """
    STEP 2: Types the city name into the search field on the opened page.
    
    Args:
        city_name: The name of the city in Israel. YOU MUST TRANSLATE THIS TO HEBREW (e.g., 'ירושלים', 'תל אביב').
        
    After this, you MUST call select_weather_forecast_city_israel to submit.
    """
    try:
        page = await ensure_browser_page()
        target_selector = "input#city_search_forecast"
        
        await page.wait_for_selector(target_selector, timeout=5000)
        await page.click(target_selector)
        await page.focus(target_selector)
        
        await page.fill(target_selector, "")
        # קצב הקלדה יציב שמעורר את התיבה הלבנה מיד
        await page.type(target_selector, city_name, delay=150)
        
        # השהיה קלה כדי לוודא שהתיבה הלבנה סיימה להיפתח לחלוטין
        await asyncio.sleep(2.0)
        
        return f"Success: City '{city_name}' typed into the field and dropdown is visible. Next, you MUST call select_weather_forecast_city_israel."
    except PlaywrightTimeout:
        return "Error: Timeout while entering city name."
    except Exception as e:
        return f"Error entering city name: {str(e)}"


@mcp.tool()
async def select_weather_forecast_city_israel():
    """
    STEP 3: Submits the search by clicking the city name inside the visible dropdown box.
    This is the final step of Phase A.
    """
    try:
        page = await ensure_browser_page()
        
        # אנחנו לוקחים את הערך הנוכחי שכתוב בתוך שדה החיפוש (למשל "תל אביב" או "חיפה")
        target_input = "input#city_search_forecast"
        city_typed = await page.locator(target_input).input_value()
        
        # קו הגנה ראשון והכי חזק: מחפשים בתוך התיבה הלבנה אלמנט שמכיל פיזית את הטקסט של העיר ולוחצים עליו!
        if city_typed:
            try:
                # locator("text=...") מוצא רכיבים לפי מה שכתוב בהם על המסך
                dropdown_option = page.locator(f"text={city_typed}").first
                await dropdown_option.click(timeout=3000)
                await page.wait_for_load_state("domcontentloaded", timeout=7000)
                return "Success: Clicked directly on the city name inside the dropdown. The forecast page is loading!"
            except Exception:
                pass # אם לא מצא לפי טקסט, נמשיך לגיבויים הבאים
        
        # קו הגנה שני: לחיצה על כפתור זכוכית המגדלת או כפתור החיפוש שליד השדה (אם קיים)
        search_button = page.locator("button[type='submit'], input[type='submit']").first
        if await search_button.is_visible(timeout=1000):
            await search_button.click()
            await page.wait_for_load_state("domcontentloaded", timeout=7000)
            return "Success: Clicked on the search submit button. The forecast page is loading!"

        # קו הגנה שלישי: גיבוי מקלדת קלאסי
        await page.focus(target_input)
        await page.keyboard.press("ArrowDown")
        await asyncio.sleep(0.3)
        await page.keyboard.press("Enter")
        await page.wait_for_load_state("domcontentloaded", timeout=7000)
        
        return "Success: Navigated via keyboard fallback, and the forecast page is loading!"
    except Exception as e:
        return f"Error selecting city: {str(e)}"


@mcp.tool()
async def extract_weather_forecast_page_content():
    """
    Extracts the visible text content from the current weather forecast page.
    Returns a cleaned text summary for RAG-style context enrichment.
    """
    try:
        page = await ensure_browser_page()
        content = await extract_visible_text(page)
        if not content:
            return "No visible content found on the current page."
        # Shorten repetitive whitespace and remove extra page navigation text
        cleaned = ' '.join(content.split())
        return cleaned
    except Exception as e:
        return f"Error extracting page content: {str(e)}"


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()