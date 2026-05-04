import math
import re
import logging
from logger_config import logger
import time
import os
import json
import pandas as pd
import requests
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup

# Constants from PDF and project requirements
EXCHANGE_RATE = 3.01
BASE_URL = "https://www.bookdelivery.com/il-en/"
MAX_PAGES_PER_CATEGORY = 5  # Reverted to 5 as per PDF
DELAY = 5
driver = None
requests_session = requests.Session()

def start_driver():
    """Initializes a standard Selenium Chrome driver (as recommended in PDF)"""
    start_time = time.time()
    logger.debug("Initializing standard Chrome driver...")
    options = Options()
    options.add_argument("--window-size=1920,1080")
    # Note: Headless is often blocked by Cloudflare, keeping it visible for manual captcha solving
    
    try:
        instance = webdriver.Chrome(options=options)
        logger.info(f"Chrome driver successfully started in {time.time() - start_time:.2f}s")
        return instance
    except Exception as e:
        logger.critical(f"FAILED TO START CHROME DRIVER: {e}", exc_info=True)
        raise

def is_blocked(soup):
    """Detects if we are on a Cloudflare challenge or Captcha page"""
    if not soup:
        return True
    
    page_text = soup.get_text().lower()
    blocking_terms = [
        "just a moment",
        "please solve the captcha",
        "verify you are a human",
        "checking your browser",
        "access denied",
        "enable cookies"
    ]
    
    # If the page title is missing or very short, it's often a block
    if not soup.title or "verify" in soup.title.get_text().lower():
        return True

    for term in blocking_terms:
        if term in page_text:
            return True
            
    return False

def sync_cookies():
    """Transfers cookies from Selenium to the Requests session"""
    global driver, requests_session
    if driver:
        logger.debug("Syncing Selenium cookies to Requests session...")
        for cookie in driver.get_cookies():
            requests_session.cookies.set(cookie['name'], cookie['value'])
        # Also set a realistic User-Agent for requests
        user_agent = driver.execute_script("return navigator.userAgent")
        requests_session.headers.update({"User-Agent": user_agent})

def get_soup_via_selenium(url, delay=5):
    """Uses Selenium for navigation and links extraction (handles JS/Captcha)"""
    global driver

    if driver is None:
        driver = start_driver()

    logger.info(f"Navigating to: {url}")
    try:
        driver.get(url)
    except Exception as e:
        logger.error(f"Navigation error for {url}: {e}")
        return None

    # Verification loop
    while True:
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        
        if is_blocked(soup):
            logger.warning("=== MANUAL INTERVENTION REQUIRED ===")
            logger.warning(f"Verification required for: {url}")
            logger.info("Please solve the captcha in the browser window. The script will wait.")
            time.sleep(5) # Check every 5 seconds
        else:
            # Check if we have actual content (e.g., categories or book links)
            if "bookdelivery" in html.lower():
                break
            else:
                logger.debug("Waiting for page content to populate...")
                time.sleep(2)

    sync_cookies() # Ensure requests has the latest session tokens
    time.sleep(delay) # Politeness delay
    return BeautifulSoup(driver.page_source, "html.parser")

def get_soup_via_requests(url):
    """Uses requests for individual book pages as strictly required by Step 1.4 of the PDF"""
    global requests_session
    
    logger.debug(f"Requesting book page: {url}")
    try:
        response = requests_session.get(url, timeout=20)
        if response.status_code != 200:
            logger.error(f"Request failed for {url} with status {response.status_code}")
            return None
        
        soup = BeautifulSoup(response.text, "html.parser")
        if is_blocked(soup):
            logger.warning(f"Requests session blocked for {url}. Captcha may have expired.")
            return None
            
        return soup
    except Exception as e:
        logger.error(f"Request exception for {url}: {e}")
        return None

def get_category_links(home_soup):
    if not home_soup:
        return {}

    logger.info("Extracting category links...")
    category_links = {}
    for a in home_soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = a["href"]
        full_url = urljoin(BASE_URL, href)
        
        if text and full_url.startswith("https://www.bookdelivery.com/il-en/books/"):
            if text not in category_links:
                category_links[text] = full_url
                logger.debug(f"Found Category: {text}")

    if not category_links:
        logger.error("Failed to find any category links!")
        
    return category_links

def get_book_links_from_category_page(category_soup):
    if not category_soup:
        return []
    
    book_links = set()
    for a in category_soup.find_all("a", href=True):
        href = a["href"]
        full_url = urljoin(BASE_URL, href)
        if "/book-" in full_url and "/p/" in full_url:
            book_links.add(full_url)

    return list(book_links)

def make_page_url(category_url, page_num):
    if page_num == 1:
        return category_url
    separator = "&" if "?" in category_url else "?"
    return f"{category_url}{separator}page={page_num}"

def crawl_bookdelivery():
    global driver
    all_books = []
    visited_books = set()
    total_start_time = time.time()

    logger.info("=== Starting Crawl (Instruction Compliant Mode) ===")
    
    home_soup = get_soup_via_selenium(BASE_URL)
    categories = get_category_links(home_soup)

    for cat_name, cat_url in categories.items():
        logger.info(f"Processing Category: {cat_name}")
        previous_page_books = set()

        for page_num in range(1, MAX_PAGES_PER_CATEGORY + 1):
            page_url = make_page_url(cat_url, page_num)
            logger.info(f"  Page {page_num}: {page_url}")

            cat_soup = get_soup_via_selenium(page_url)
            book_links = get_book_links_from_category_page(cat_soup)

            if not book_links:
                logger.warning(f"  No books found on page {page_num}. This might be a block or end of list.")
                break

            if set(book_links) == previous_page_books:
                logger.info("  Reached duplicate page (end of category).")
                break
            previous_page_books = set(book_links)

            for book_url in book_links:
                if book_url in visited_books:
                    continue
                visited_books.add(book_url)

                try:
                    book_soup = get_soup_via_requests(book_url)
                    if not book_soup:
                        logger.info("  Refreshing session via Selenium...")
                        get_soup_via_selenium(book_url)
                        book_soup = get_soup_via_requests(book_url)

                    if book_soup:
                        book_data = get_book_data_from_soup(book_soup, cat_name, book_url)
                        all_books.append(book_data)
                        logger.info(f"    Indexed: {book_data.get('Title', 'Unknown')}")
                except Exception as e:
                    logger.error(f"    Failed {book_url}: {e}")

                time.sleep(DELAY)

    if driver:
        driver.quit()
        driver = None

    logger.info(f"Crawl Done. Total: {len(all_books)} books. Time: {time.time() - total_start_time:.2f}s")
    return all_books

def extract_star_rating(soup):
    rating_bars = soup.find_all('div', class_='rating-bar')
    if not rating_bars: return "None"
    total_stars, total_votes = 0, 0
    for bar in rating_bars:
        try:
            stars = int(re.search(r'\d+', bar.find('span', class_='star-label').get_text()).group())
            votes = int(re.search(r'\d+', bar.find('span', class_='vote-count').get_text()).group())
            total_stars += stars * votes
            total_votes += votes
        except: continue
    return math.ceil((total_stars / total_votes) * 100) / 100 if total_votes > 0 else "None"

def get_book_data_from_soup(soup, category_source, book_url):
    page_text = soup.get_text(" ", strip=True)
    title = soup.find('h1').get_text(strip=True) if soup.find('h1') else "None"
    authors = ", ".join([a.get_text(strip=True) for a in soup.find_all('a', class_='font-color-bl link-underline')])
    
    price_nis = 0.0
    prices = [float(p) for p in re.findall(r"₪\s*([0-9]+(?:\.[0-9]+)?)", page_text)]
    book_prices = [p for p in prices if p > 40]
    if book_prices:
        price_nis = math.ceil(min(book_prices) * 100) / 100
    price_usd = math.ceil((price_nis / EXCHANGE_RATE) * 100) / 100

    meta_match = re.search(r"Type\s+Physical Book(.+?)ISBN13\s+\d+", page_text, re.IGNORECASE)
    meta_block = meta_match.group(1) if meta_match else ""
    
    def extract_label(label):
        match = re.search(label + r"\s+(.+?)\s+(?=Type|Author|Publisher|Collection|Year|Language|Pages|Format|Dimensions|Weight|ISBN13|$)", meta_block, re.IGNORECASE)
        return match.group(1).strip() if match else "None"

    isbn_match = re.search(r"ISBN13\s+(\d+)", page_text, re.IGNORECASE)
    dim_raw = extract_label("Dimensions")
    weight_raw = extract_label("Weight")

    return {
        'url': book_url, 'Title': title, 'Category_Source': category_source, 
        'Categories': category_source, 'Authors': authors, 'Price NIS': price_nis, 'Price USD': price_usd,
        'Year': extract_label("Year"), 'Synopsis': "", 'Synopsis Length': 0, 
        'StarRating': extract_star_rating(soup), 'NumberOfReviews': 0,
        'Language': extract_label("Language"), 'Format': extract_label("Format"),
        'Dimensions': ", ".join(re.findall(r'[0-9.]+', dim_raw)), 'Dimensions unit': "cm" if "cm" in dim_raw.lower() else "",
        'Weight': "".join(re.findall(r'[0-9.]+', weight_raw)), 'Weight Unit': "kg" if "kg" in weight_raw.lower() else "gr",
        'ISBN': isbn_match.group(1) if isbn_match else "None"
    }

def cast_numeric(all_books):
    df = pd.DataFrame(all_books)
    for col in ['Price NIS', 'Price USD', 'Year']:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
    return df

def file_export(df):
    os.makedirs("output", exist_ok=True)
    df.to_csv("output/books_raw.csv", index=False, encoding="utf-8-sig")
    records = [{"id": str(i+1), **{k: v for k, v in row.items() if pd.notnull(v) and v != "None"}} for i, row in df.iterrows()]
    with open("output/books_raw.json", "w", encoding="utf-8") as f:
        json.dump({"records": {"record": records}}, f, indent=4, ensure_ascii=False)

def preview_and_sort(df):
    df.head(10).to_csv("output/books_before_sort.csv", index=False, encoding="utf-8-sig")
    df_sorted = df.sort_values(by="Title").head(10)
    df_sorted.to_csv("output/books_after_sort.csv", index=False, encoding="utf-8-sig")
    return df

def process_data(df):
    median_price = df['Price NIS'].median()
    df['IsExpensive'] = (df['Price NIS'] > median_price).astype(int)
    df['NumberOfAuthors'] = df['Authors'].apply(lambda x: len(str(x).split(',')) if x != "None" else 0)
    df.to_csv("output/books_processed.csv", index=False, encoding="utf-8-sig")
    return df

def calculate_summary_statistics(df):
    summary = df[['Price USD', 'Year']].describe().T
    summary['total_rows'] = len(df)
    summary.to_csv("output/books_summary.csv")
    return summary

if __name__ == "__main__":
    try:
        data = crawl_bookdelivery()
        if data:
            df = cast_numeric(data)
            file_export(df)
            preview_and_sort(df)
            df = process_data(df)
            calculate_summary_statistics(df)
            logger.info("Process Complete")
    except Exception as e:
        logger.critical(f"App Crash: {e}", exc_info=True)
