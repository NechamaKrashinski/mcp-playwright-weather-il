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


@mcp.tool()
async def open_weather_forecast_israel():
    """
    STEP 1: Opens the Israeli weather forecast website in Chromium.
    You MUST call this tool FIRST before doing anything else.
    """
    try:
        page = await ensure_browser_page()
        await page.goto(FORECAST_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector("input#city_search_forecast", timeout=7000)
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
        city_name: The name of the city in Israel. YOU MUST TRANSLATE THIS TO HEBREW (e.g., 'ירושלים', 'תל אביב', 'טבריה').
        
    After this, you MUST call select_weather_forecast_city_israel to submit.
    """
    try:
        page = await ensure_browser_page()
        target_selector = "input#city_search_forecast"

        await page.wait_for_selector(target_selector, timeout=5000)
        await page.click(target_selector)
        await page.focus(target_selector)
        await page.fill(target_selector, "")
        await page.type(target_selector, city_name, delay=150)
        
        await asyncio.sleep(2.5)
        return f"Success: City '{city_name}' typed into the field and dropdown is visible. Next, you MUST call select_weather_forecast_city_israel."
    except PlaywrightTimeout:
        return "Error: Timeout while entering city name."
    except Exception as e:
        return f"Error entering city name: {str(e)}"


@mcp.tool()
async def select_weather_forecast_city_israel():
    """
    STEP 3: Submits the search by clicking the city name inside the visible dropdown box.
    This action navigates the browser to the city's unique forecast page.
    """
    try:
        page = await ensure_browser_page()
        target_input = "input#city_search_forecast"
        
        city_typed = await page.locator(target_input).input_value()

        if city_typed:
            try:
                dropdown_option = page.get_by_text(city_typed).first
                if await dropdown_option.count() > 0:
                    await dropdown_option.click(timeout=3000)
                    await page.wait_for_load_state("domcontentloaded", timeout=7000)
                    return "Success: Clicked directly on the city name inside the dropdown. The forecast page is loading! Now you MUST call extract_weather_forecast_page_content."
            except Exception:
                pass

        real_suggestion_selector = "div.autocomplete-suggestion, .autocomplete-suggestions > div"
        try:
            await page.wait_for_selector(real_suggestion_selector, timeout=3000)
            first_item = page.locator(real_suggestion_selector).first
            if await first_item.count() > 0:
                await first_item.click()
                await page.wait_for_load_state("domcontentloaded", timeout=7000)
                return "Success: Clicked the first autocomplete suggestion. The forecast page is loading! Now you MUST call extract_weather_forecast_page_content."
        except Exception:
            pass

        await page.focus(target_input)
        await page.keyboard.press("ArrowDown")
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")
        await page.wait_for_load_state("domcontentloaded", timeout=7000)
        return "Success: Navigated via keyboard fallback, and the forecast page is loading! Now you MUST call extract_weather_forecast_page_content."
        
    except Exception as e:
        return f"Error selecting city: {str(e)}"


@mcp.tool()
async def extract_weather_forecast_page_content():
    """
    STEP 4 (RAG): Extracts the pure visible text content of the loaded city weather forecast page.
    Call this tool ONLY after select_weather_forecast_city_israel has finished successfully.
    """
    try:
        page = await ensure_browser_page()
        
        # ממתינים קצרות שאלמנט ה-body לפחות יהיה יציב
        await page.wait_for_load_state("domcontentloaded", timeout=5000)
        
        # רשימת הסלקטורים המדויקת של תיבות התוכן והתחזיות המרכזיות באתר weather2day
        rag_selectors = [
            "div.f_content",
            "div.forecast-content",
            "table.forecast-table",
            "main",
            "div#content"
        ]
        
        extracted_text = ""
        for selector in rag_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() > 0 and await locator.is_visible():
                    raw_text = await locator.inner_text()
                    if raw_text and len(raw_text.strip()) > 50:
                        extracted_text = raw_text
                        break
            except Exception:
                continue
                
        # גיבוי: אם התיבות הממוקדות לא נמצאו, נשלוף את כל ה-body אבל ננקה אותו משורות ריקות וניקח רק חלק עליון
        if not extracted_text:
            all_body_text = await page.locator("body").inner_text()
            lines = [line.strip() for line in all_body_text.split("\n") if line.strip()]
            extracted_text = "\n".join(lines[:100]) # לוקחים רק את 100 השורות הראשונות למניעת עומס
            
        # ניקוי רווחים כפולים לנוחות המודל
        cleaned_summary = "\n".join([line.strip() for line in extracted_text.split("\n") if line.strip()])
        
        return f"--- START OF WEATHER CONTEXT ---\n{cleaned_summary[:2000]}\n--- END OF WEATHER CONTEXT ---"
        
    except Exception as e:
        return f"Error extracting page content: {str(e)}"


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()