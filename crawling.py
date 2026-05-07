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
from selenium.webdriver.chrome.service import Service
from bs4 import BeautifulSoup
import numpy as np

# Constants from PDF and project requirements
EXCHANGE_RATE = 3.01
BASE_URL = "https://www.bookdelivery.com"
# TARGET_TOTAL_BOOKS = 5000  # New requirement
MAX_PAGES_PER_CATEGORY = 5
DELAY = 3
driver = None
RESET_CRAWL = True
requests_session = requests.Session()


def start_driver():
    """Starts a fresh Chrome driver with stealth flags. Kills any old driver first."""
    global driver
    # Kill old driver if it exists
    if driver is not None:
        try:
            driver.quit()
        except:
            pass
        driver = None

    options = Options()
    options.add_argument("--window-size=1920,1080")

    # Friend's stealth flags
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    try:
        service = Service()
        driver = webdriver.Chrome(service=service, options=options)

        # Hide the "navigator.webdriver" flag from JavaScript
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            """
        })

        logger.info("Stealth Chrome driver started.")
        return driver
    except Exception as e:
        logger.critical(f"FAILED TO START CHROME DRIVER: {e}")
        raise


def is_blocked(soup):
    """Detects if blocked by Cloudflare/Captcha"""
    if not soup: return True
    page_text = soup.get_text().lower()
    blocking_terms = ["just a moment", "solve the captcha", "verify you are a human", "access denied"]
    if not soup.title or "verify" in soup.title.get_text().lower(): return True
    for term in blocking_terms:
        if term in page_text: return True
    return False


def sync_cookies():
    """Syncs Selenium session to Requests session"""
    global driver, requests_session
    if driver:
        for cookie in driver.get_cookies():
            requests_session.cookies.set(cookie['name'], cookie['value'])
        user_agent = driver.execute_script("return navigator.userAgent")
        requests_session.headers.update({"User-Agent": user_agent})


def get_soup_via_selenium(url, delay=5):
    """Navigates with Selenium. Restarts driver if session dies."""
    global driver
    for attempt in range(3):
        try:
            if driver is None:
                start_driver()

            driver.get(url)

            # Wait for real content (not captcha)
            for _ in range(30):  # max 60 seconds waiting
                try:
                    html = driver.page_source
                except Exception:
                    # Session died while reading page — restart
                    logger.warning("Session died during page_source read. Restarting driver...")
                    start_driver()
                    break  # break inner loop, retry outer loop

                soup = BeautifulSoup(html, "html.parser")

                if is_blocked(soup):
                    logger.warning("=== MANUAL INTERVENTION REQUIRED: SOLVE CAPTCHA ===")
                    time.sleep(5)
                elif "bookdelivery" in html.lower():
                    # Page shell loaded — wait for JS to fully render content
                    logger.info(f"Page detected ({len(html)} bytes). Waiting for JS render...")
                    time.sleep(5)  # let JavaScript populate the page
                    html = driver.page_source  # re-read after JS render
                    logger.info(f"After JS wait: {len(html)} bytes")
                    sync_cookies()
                    time.sleep(delay)
                    return BeautifulSoup(html, "html.parser")
                else:
                    time.sleep(2)
            else:
                # Exhausted 30 checks — probably stuck on captcha
                logger.error(f"Timed out waiting for content on {url}")

        except Exception as e:
            logger.error(f"Selenium error (attempt {attempt+1}/3) for {url}: {e}")
            start_driver()  # restart on any error
            time.sleep(5)

    return None


def get_soup_via_requests(url):
    """Requests book page using the requests library (as per PDF)"""
    try:
        response = requests_session.get(url, timeout=20)
        if response.status_code != 200: return None
        soup = BeautifulSoup(response.text, "html.parser")
        return None if is_blocked(soup) else soup
    except: return None


def extract_metadata_label(meta_block, label):
    """Helper to extract specific values from the metadata text block."""
    pattern = label + r"\s+(.+?)\s+(?=Type|Author|Publisher|Collection|Year|Language|Pages|Format|Dimensions|Weight|ISBN13|Categories|$)"
    match = re.search(pattern, meta_block, re.IGNORECASE)
    return match.group(1).strip() if match else "None"

def get_star_rating(soup, num_reviews):
    """Computes StarRating from JSON-LD or hidden HTML as per PDF Step 1.4."""
    if num_reviews == 0:
        return "None"

    # Method 1: JSON-LD (Most accurate for 'Star Distribution')
    script_tag = soup.find('script', type='application/ld+json')
    if script_tag:
        try:
            data = json.loads(script_tag.string)
            if 'aggregateRating' in data:
                raw_val = float(data['aggregateRating']['ratingValue'])
                return math.ceil(raw_val * 100) / 100
        except: pass

    # Method 2: Fallback to hidden span
    val_span = soup.find('a', id='valoracion')
    if val_span:
        hidden_data = val_span.find('span', style=re.compile('display:none'))
        if hidden_data:
            try:
                raw_text = hidden_data.find('span').get_text(strip=True).replace(',', '.')
                return math.ceil(float(raw_text) * 100) / 100
            except: pass
    return "None"

def get_prices(soup):
    """Extracts product price from current book page."""

    texts = soup.find_all(string=re.compile(r'₪'))

    prices = []

    for t in texts:
        matches = re.findall(r'₪\s*(\d+(?:\.\d+)?)', str(t))

        for m in matches:
            val = float(m)

            # realistic book prices only
            if 30 <= val <= 1000:
                prices.append(val)

    if not prices:
        return 0.0, 0.0

    # usually actual product price is the highest visible price
    price_nis = max(prices)

    price_usd = round(price_nis / EXCHANGE_RATE, 2)

    return price_nis, price_usd

def get_categories_plural(soup):
    """Extracts comma-separated categories from metadata[cite: 1, 2]."""
    categories_div = soup.find('div', {'id': 'metadata-categorías'})
    if categories_div:
        links = categories_div.find_all('a')
        return ", ".join([link.get_text(strip=True) for link in links])
    return "None"

def get_book_data_from_soup(soup, category_source, book_url):
    """Orchestrates data extraction into a clean dictionary."""
    page_text = soup.get_text(" ", strip=True)

    # 1. Basic Info
    title_tag = soup.find('p', class_='tituloProducto') or soup.find('h1')
    title = title_tag.get_text(strip=True) if title_tag else "None"
    authors = ", ".join([a.get_text(strip=True) for a in soup.find_all('a', class_='font-color-bl link-underline')])

    # 2. Prices & Ratings
    price_nis, price_usd = get_prices(soup)
    num_reviews = 0
    rev_match = re.search(r'(\d+)\s+reviews', page_text, re.IGNORECASE)
    if rev_match: num_reviews = int(rev_match.group(1))
    star_rating = get_star_rating(soup, num_reviews)

    # 3. Metadata block parsing
    meta_match = re.search(r"Type\s+Physical Book(.+?)ISBN13\s+\d+", page_text, re.IGNORECASE)
    meta_block = meta_match.group(1) if meta_match else ""

    dim_raw = extract_metadata_label(meta_block, "Dimensions")
    weight_raw = extract_metadata_label(meta_block, "Weight")
    syn_match = re.search(r"Synopsis\s+(.+?)\s+Translate to english", page_text, re.IGNORECASE)
    synopsis = syn_match.group(1).strip() if syn_match else ""

    return {
        'url': book_url,
        'Title': title,
        'Category': category_source,  # Where you crawled it from
        'Categories': get_categories_plural(soup),  # From page tags
        'Authors': authors,
        'Price NIS': price_nis,
        'Price USD': price_usd,
        'Year': extract_metadata_label(meta_block, "Year"),
        'Synopsis': synopsis,
        'Synopsis Length': len(synopsis),
        'StarRating': star_rating,
        'NumberOfReviews': num_reviews,
        'Language': extract_metadata_label(meta_block, "Language"),
        'Format': extract_metadata_label(meta_block, "Format"),
        'Dimensions': ", ".join(re.findall(r'[0-9.]+', dim_raw)),
        'Dimensions unit': "cm" if "cm" in dim_raw.lower() else "",
        'Weight': "".join(re.findall(r'[0-9.]+', weight_raw)),
        'Weight Unit': "kg" if "kg" in weight_raw.lower() else "gr",
        'ISBN': re.search(r"ISBN13\s+(\d+)", page_text, re.IGNORECASE).group(1) if re.search(r"ISBN13\s+(\d+)",
                                                                                             page_text,
                                                                                             re.IGNORECASE) else "None"
    }

def crawl_bookdelivery():
    global driver
    all_books = []
    visited_urls = set()

    # Resume Progress
    if not RESET_CRAWL and os.path.exists("output/books_raw.csv"):
        try:
            df_old = pd.read_csv("output/books_raw.csv")
            all_books = df_old.to_dict('records')
            visited_urls = set(df_old['url'].tolist())
            logger.info(f"Resuming with {len(all_books)} books.")
        except Exception as e:
            logger.warning(f"Could not resume correctly: {e}, starting fresh.")

    home_soup = get_soup_via_selenium(BASE_URL)
    if home_soup is None:
        logger.error("Failed to load home page.")
        return all_books

    categories = {}
    for a in home_soup.find_all("a", href=True):
        href = a["href"]
        if "/il-en/books/" in href and "/book-" not in href:
            name = a.get_text(strip=True)
            if name:
                categories[name] = href if href.startswith("http") else urljoin(BASE_URL, href)

    logger.info(f"Found {len(categories)} categories to explore.")

    for cat_name, cat_url in categories.items():

        print("\n" + "=" * 80)
        print(f" CATEGORY START: {cat_name}")
        print("=" * 80)

        prev_links = set()

        for page_num in range(1, MAX_PAGES_PER_CATEGORY + 1):

            url = f"{cat_url}{'&' if '?' in cat_url else '?'}page={page_num}" if page_num > 1 else cat_url

            print(f"\n Page {page_num} | URL: {url}")

            soup = get_soup_via_selenium(url)
            if soup is None:
                print(f" Failed page {page_num} in {cat_name}")
                break

            raw_links = [
                urljoin(BASE_URL, a["href"])
                for a in soup.find_all("a", href=True)
                if "/book-" in a["href"] and "/p/" in a["href"]
            ]
            links = list(
                dict.fromkeys(raw_links))

            if not links:
                print(" No books found on page — stopping category early.")
                break

            if set(links) == prev_links:
                print(" Pagination loop detected — stopping category.")
                break

            prev_links = set(links)

            for i, link in enumerate(links, 1):

                if link in visited_urls:
                    continue

                visited_urls.add(link)

                print(f"\n [{len(all_books)+1}] Loading book {i}/{len(links)}")
                print(f"{link}")

                book_soup = get_soup_via_requests(link)

                if not book_soup:
                    print("Requests failed — retrying with Selenium")
                    book_soup = get_soup_via_selenium(link)

                if book_soup:
                    try:
                        data = get_book_data_from_soup(book_soup, cat_name, link)
                        all_books.append(data)

                        print(f" TITLE: {data['Title']}")
                        print(f"Price NIS: {data['Price NIS']} | USD: {data['Price USD']}")
                        print(f"Rating: {data['StarRating']}")
                        print(f"Number of Rating: {data['NumberOfReviews']}")
                        print(f"Category: {data['Category']}")
                        print(f"Categories: {data['Categories']}")
                        print(f" Authors: {data['Authors']}")
                        print("-" * 60)

                        # Save progress every 5 books
                        if len(all_books) % 5 == 0:
                            pd.DataFrame(all_books).to_csv(
                                "output/books_raw.csv",
                                index=False,
                                encoding="utf-8-sig"
                            )

                    except Exception as e:
                        print(f" Error parsing book: {e}")

                time.sleep(DELAY)
    return all_books


def process_and_save(data):
    df = pd.DataFrame(data)
    os.makedirs("output", exist_ok=True)
    
    # Step 1: Cast Numeric
    for c in ['Price NIS', 'Price USD', 'Year', 'StarRating', 'NumberOfReviews', 'Synopsis Length']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    
    # Step 2.2: Raw JSON
    def save_j(df_in, path):
        recs = []
        for i, r in df_in.iterrows():
            row_dict = {"id": str(i + 1)}
            for k, v in r.items():
                if pd.notnull(v) and v is not None and str(
                        v).strip().lower() != "none" and str(v).strip() != "":
                    row_dict[k] = v
            recs.append(row_dict)

        with open(path, "w", encoding="utf-8") as f:
            json.dump({"records": {"record": recs}}, f, indent=4,
                      ensure_ascii=False)

    df.to_csv("output/books_raw.csv", index=False, encoding="utf-8-sig")
    save_j(df, "output/books_raw.json")
    
    # Step 3: Sorting
    df.head(10).to_csv("output/books_before_sort.csv", index=False, encoding="utf-8-sig")
    df_sorted = df.sort_values(by="Title")
    df_sorted.head(10).to_csv("output/books_after_sort.csv", index=False, encoding="utf-8-sig")
    
    # Step 4: Features
    if 'Price NIS' in df.columns:
        df['IsExpensive'] = (df['Price NIS'] > df['Price NIS'].median()).astype(int)
    if 'Authors' in df.columns:
        df['NumberOfAuthors'] = df['Authors'].apply(lambda x: len([a for a in str(x).split(',') if a.strip()]) if x != "None" else 0)
    df.to_csv("output/books_processed.csv", index=False, encoding="utf-8-sig")
    save_j(df, "output/books_processed.json")
    df.head(10).to_csv("output/books_processed_preview.csv", index=False, encoding="utf-8-sig")
    
    # Step 5: Summary
    cols = ['Price USD', 'Year', 'StarRating', 'NumberOfReviews', 'NumberOfAuthors']
    existing_cols = [c for c in cols if c in df.columns]
    summary = df[existing_cols].agg(['mean', 'std', 'min', 'max', 'median']).T
    summary['total_rows'] = len(df)
    summary.to_csv("output/books_summary.csv")
    
    # Step 2.3: Example
    save_j(df.head(1), "output/books_example.json")
    # logger.info("All output files generated.")

if __name__ == "__main__":
        try:
            final_data = crawl_bookdelivery()
            if final_data:
                process_and_save(final_data)
                # if len(final_data) >= TARGET_TOTAL_BOOKS:
                #     logger.info("Target reached. Script terminating.")
                #     break
                # else:
                #     logger.info(f"Crawled {len(final_data)} books. Target not yet met. Restarting loop...")
            else:
                # logger.warning("No data returned. Retrying in 1 minute...")
                time.sleep(60)
        except Exception as e:
            # logger.critical(f"Main loop crash: {e}. Restarting in 1 minute...", exc_info=True)
            time.sleep(60)
