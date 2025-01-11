import aiohttp
import random
import re
import asyncio
import logging
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from bs4 import BeautifulSoup

# Command for running code


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# Set up template rendering
templates = Jinja2Templates(directory="templates")

# Mixed User-Agent headers to mimic a typical browser and bypass rate limits
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 Edge/91.0.864.64",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
]


# Function to scrape Amazon for product data using aiohttp (async)
async def scrape_amazon(input_value: str):
    # Check if the input is a full URL or just an ASIN
    if "amazon.com" in input_value:
        # Extract ASIN from the URL
        asin = extract_asin_from_url(input_value)
        url = f"https://www.amazon.com/dp/{asin}"
    else:
        # It's an ASIN, construct the URL
        asin = input_value
        url = f"https://www.amazon.com/dp/{asin}"

    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9"
    }

    # Simulate human-like browsing by introducing delays
    await asyncio.sleep(random.uniform(2, 5))  # Random delay between 2-5 seconds

    # Send a request to the product page using aiohttp (rate limit bypass)
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status != 200:
                    # Log non-200 status codes for debugging purposes
                    logger.warning(f"Failed to fetch product page: {url} (status code: {response.status})")
                    if response.status == 403:
                        return {"error": "Access Denied: Amazon blocked the request."}
                    elif response.status == 404:
                        return {"error": "Product not found."}
                    else:
                        return {"error": "An error occurred while fetching the product."}

                html = await response.text()

    except aiohttp.ClientTimeout:
        logger.error(f"Timeout while accessing {url}")
        return {"error": "Request to Amazon timed out."}
    except aiohttp.ClientError as e:
        logger.error(f"Client error while accessing {url}: {e}")
        return {"error": f"Error during the request to Amazon: {str(e)}"}
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return {"error": f"Unexpected error: {str(e)}"}

    # Parse HTML with BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')

    # Extract product name
    try:
        product_name = soup.find('span', {'id': 'productTitle'}).get_text(strip=True)
    except AttributeError:
        product_name = "Unknown"

    # Extract product price
    price = "0"
    try:
        # Try multiple potential price elements
        price = soup.find('span', {'id': 'priceblock_ourprice'}) or \
                soup.find('span', {'id': 'priceblock_dealprice'}) or \
                soup.find('span', {'class': 'a-price-whole'}) or \
                soup.find('span', {'class': 'a-price-symbol'}) or \
                soup.find('span', {'class': 'aok-offscreen'}) or \
                soup.find('span', {'class': 'a-price'})  # Sometimes wrapped inside 'a-price' class

        # Extract the price text if found
        if price:
            price = price.get_text(strip=True)

        # Handle cases where price is split into whole and fractional parts
        if not price:
            whole_part = soup.find('span', {'class': 'a-price-whole'})
            fractional_part = soup.find('span', {'class': 'a-price-symbol'})
            if whole_part and fractional_part:
                price = f"{whole_part.get_text(strip=True)}{fractional_part.get_text(strip=True)}"

        # If no price found, set as "Price not available"
        if not price:
            price = "Price not available"

    except Exception as e:
        logger.error(f"Error extracting product price: {e}")
        price = "Price not available"

    # Detect product condition (new, used, refurbished)
    product_grade = "Condition not specified"
    try:
        # Extract the text from the merchant-info div
        condition = soup.find('div', {'id': 'merchant-info'})
        if condition:
            condition_text = condition.get_text(strip=True)
            logger.info(f"Condition text: {condition_text}")  # Log the raw condition text for debugging

            # Use regex to search for known conditions (New, Used, Refurbished)
            grade = re.search(r'(New|Used|Refurbished)', condition_text, re.IGNORECASE)
            if grade:
                product_grade = grade.group(0)
            else:
                logger.info("Condition not found in the merchant-info section.")
        else:
            logger.info("No merchant-info section found.")

    except Exception as e:
        logger.error(f"Error extracting product condition: {e}")

    return {"product_name": product_name, "price": price, "grade": product_grade, "url": url, "asin": asin}


def extract_asin_from_url(url: str):
    # Extract the ASIN from a full Amazon product URL
    match = re.search(r"/dp/([A-Z0-9]{10})", url)
    return match.group(1) if match else None


# Root endpoint to render the HTML page
@app.get("/", response_class=HTMLResponse)
async def get_form(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# Endpoint to scrape Amazon product data
@app.post("/scrape_amazon/", response_class=HTMLResponse)
async def scrape_product(request: Request, input_value: str = Form(...)):
    logger.info(f"Received input_value: {input_value}")  # Debugging: Log the received value

    product_info = await scrape_amazon(input_value)

    # Check if there is an error returned
    if "error" in product_info:
        return templates.TemplateResponse("index.html", {"request": request, "error": product_info["error"]})

    # Pass product info to the template
    return templates.TemplateResponse("index.html", {
        "request": request,
        "product": product_info,
        "dbg_url": product_info['url'],
        "dbg_asin": product_info['asin']
    })
