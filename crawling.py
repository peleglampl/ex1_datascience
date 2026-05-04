import math
import re
import logging
from logger_config import logger
import time
import os
import json
import pandas as pd
from urllib.parse import urljoin
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

EXCHANGE_RATE = 3.01
BASE_URL = "https://www.bookdelivery.com/il-en/"
MAX_PAGES_PER_CATEGORY = 10  # Increased from 5
DELAY = 5
driver = None

# Persistence: Path for saving browser session (cookies, trust, etc.)
USER_DATA_DIR = os.path.join(os.getcwd(), "chrome_session")

def start_driver():
    start_time = time.time()
    logger.debug("Initializing Undetected Chrome Driver with session persistence...")
    
    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={USER_DATA_DIR}")
    options.add_argument("--window-size=1920,1080")
    
    # Fix for hanging in some environments
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    
    try:
        # Undetected-chromedriver handles the bypass naturally
        instance = uc.Chrome(options=options, headless=False) 
        logger.info(f"Undetected Chrome driver started in {time.time() - start_time:.2f}s")
        return instance
    except Exception as e:
        logger.critical(f"FAILED TO START UC DRIVER: {e}", exc_info=True)
        raise

def is_blocked(soup):
    """Check if we are hitting a Cloudflare challenge or captcha page"""
    if not soup:
        return True
    
    page_text = soup.get_text().lower()
    blocking_terms = [
        "just a moment",
        "please solve the captcha",
        "verify you are a human",
        "checking your browser",
        "access denied"
    ]
    
    for term in blocking_terms:
        if term in page_text:
            return True
    return False

def get_soup_from_url(url, delay=5):
    global driver

    logger.debug(f"Fetching: {url}")
    if driver is None:
        driver = start_driver()

    try:
        driver.get(url)
    except Exception as e:
        logger.error(f"Transport error for {url}: {e}")
        return None

    # Initial check for blocking
    html = driver.page_source
    soup = BeautifulSoup(html, "html.parser")
    
    if is_blocked(soup):
        logger.warning(f"=== BLOCK DETECTED at {url} ===")
        logger.info("The site is asking for verification. Please solve it in the browser window.")
        # We wait until the blocking text is gone or a specific element appears
        timeout = 300 # 5 minutes
        start_wait = time.time()
        while is_blocked(soup) and (time.time() - start_wait < timeout):
            time.sleep(2)
            html = driver.page_source
            soup = BeautifulSoup(html, "html.parser")
            
        if is_blocked(soup):
            logger.error("Timed out waiting for manual verification.")
            return None
        else:
            logger.info("Verification cleared. Continuing...")

    logger.debug(f"Waiting {delay}s...")
    time.sleep(delay)

    try:
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        return soup
    except Exception as e:
        logger.error(f"Parse error for {url}: {e}")
        return None


def get_category_links(home_soup):
    if not home_soup:
        logger.error("get_category_links received empty soup")
        return {}

    logger.info("Starting category extraction from homepage...")
    category_links = {}

    for a in home_soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = a["href"]
        full_url = urljoin(BASE_URL, href)

        if not text:
            continue

        if not full_url.startswith("https://www.bookdelivery.com/il-en/books/"):
            continue

        if text in category_links:
            continue
            
        category_links[text] = full_url
        logger.debug(f"Registered Category: [{text}] -> {full_url}")

    logger.info(f"Extraction complete. Found {len(category_links)} valid categories.")
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

    logger.info("Initializing Crawler Session...")
    
    home_soup = get_soup_from_url(BASE_URL)
    if not home_soup:
        logger.critical("Could not load homepage. Aborting crawl.")
        return []

    categories = get_category_links(home_soup)

    for category_idx, (category_name, category_url) in enumerate(categories.items()):
        cat_start_time = time.time()
        logger.info(f"Processing Category {category_idx+1}/{len(categories)}: {category_name}")

        previous_page_books = set()

        for page_num in range(1, MAX_PAGES_PER_CATEGORY + 1):
            page_url = make_page_url(category_url, page_num)
            logger.info(f"  Scanning Page {page_num}: {page_url}")

            category_soup = get_soup_from_url(page_url)
            if not category_soup:
                logger.error(f"  Failed to retrieve content for page {page_num}. Skipping category.")
                break

            book_links = get_book_links_from_category_page(category_soup)

            if not book_links:
                logger.info("  No book links found. Ending category pagination.")
                break

            current_page_books = set(book_links)
            if current_page_books == previous_page_books:
                logger.info("  Detected duplicate content (pagination end).")
                break

            previous_page_books = current_page_books
            logger.info(f"  Discovered {len(book_links)} books on this page.")

            for book_url in book_links:
                if book_url in visited_books:
                    continue

                visited_books.add(book_url)

                try:
                    logger.debug(f"    Retrieving details for: {book_url}")
                    book_soup = get_soup_from_url(book_url)
                    if not book_soup:
                        continue

                    book_data = get_book_data_from_soup(
                        book_soup,
                        category_source=category_name,
                        book_url=book_url
                    )

                    all_books.append(book_data)
                    logger.info(f"    Successfully indexed: {book_data.get('Title', 'Unknown')}")

                except Exception as e:
                    logger.error(f"    Error processing book {book_url}: {e}", exc_info=True)

                time.sleep(DELAY)

        logger.info(f"Finished category '{category_name}' in {time.time() - cat_start_time:.2f}s")
            
    if driver is not None:
        logger.info("Terminating Selenium session.")
        driver.quit()
        driver = None

    logger.info(f"Crawl completed. Total books: {len(all_books)}. Total time: {time.time() - total_start_time:.2f}s")
    return all_books


def extract_star_rating(soup):
    rating_bars = soup.find_all('div', class_='rating-bar')
    if not rating_bars:
        return "None"

    total_stars = 0
    total_votes = 0

    for bar in rating_bars:
        try:
            star_label = bar.find('span', class_='star-label')
            vote_label = bar.find('span', class_='vote-count')
            if not star_label or not vote_label: continue
                
            stars = int(re.search(r'\d+', star_label.get_text(strip=True)).group())
            votes = int(re.search(r'\d+', vote_label.get_text(strip=True)).group())

            total_stars += stars * votes
            total_votes += votes
        except Exception:
            continue

    if total_votes == 0:
        return "None"

    return math.ceil((total_stars / total_votes) * 100) / 100


def get_book_data_from_soup(soup, category_source, book_url):
    page_text = soup.get_text(" ", strip=True)

    title_h1 = soup.find('h1')
    title = title_h1.get_text(strip=True) if title_h1 else "None"

    authors_elements = soup.find_all('a', class_='font-color-bl link-underline')
    authors = ", ".join([a.get_text(strip=True) for a in authors_elements])

    price_nis = 0.0
    price_usd = 0.0
    prices = [float(p) for p in re.findall(r"₪\s*([0-9]+(?:\.[0-9]+)?)", page_text)]
    book_prices = [p for p in prices if p > 40]

    if book_prices:
        price_nis = math.ceil(min(book_prices) * 100) / 100
        price_usd = math.ceil((price_nis / EXCHANGE_RATE) * 100) / 100

    meta_block = ""
    match = re.search(r"Type\s+Physical Book(.+?)ISBN13\s+\d+", page_text, re.IGNORECASE)
    if match:
        meta_block = match.group(1)

    def extract_between_labels(block, label, next_labels):
        pattern = label + r"\s+(.+?)\s+(?=" + "|".join(next_labels) + r"|$)"
        match = re.search(pattern, block, re.IGNORECASE)
        return match.group(1).strip() if match else "None"

    labels = ["Type", "Author", "Publisher", "Collection", "Year", "Language", "Pages", "Format", "Dimensions", "Weight", "ISBN13"]
    year = extract_between_labels(meta_block, "Year", labels)
    language = extract_between_labels(meta_block, "Language", labels)
    format_book = extract_between_labels(meta_block, "Format", labels)
    dim_raw = extract_between_labels(meta_block, "Dimensions", labels)
    weight_raw = extract_between_labels(meta_block, "Weight", labels)
    isbn_match = re.search(r"ISBN13\s+(\d+)", page_text, re.IGNORECASE)
    isbn = isbn_match.group(1) if isbn_match else "None"

    dim_numbers = ", ".join(re.findall(r'[0-9.]+', dim_raw))
    dim_unit = "cm" if "cm" in dim_raw.lower() else ("inch" if "inch" in dim_raw.lower() else "")

    if weight_raw == "None":
        weight_num, weight_unit = "", ""
    else:
        weight_num = "".join(re.findall(r'[0-9.]+', weight_raw))
        weight_unit = "pounds" if "pound" in weight_raw.lower() else ("kg" if "kg" in weight_raw.lower() else "gr")

    synopsis = ""
    syn_match = re.search(r"Synopsis\s+(.+?)\s+Translate to english", page_text, re.IGNORECASE)
    if syn_match:
        synopsis = syn_match.group(1).strip()

    breadcrumb_wrap = soup.find('div', class_='breadcrumb-wrapper')
    if breadcrumb_wrap:
        cat_list = [a.get_text(strip=True) for a in breadcrumb_wrap.find_all('a')]
        categories = ", ".join(cat_list[1:]) if len(cat_list) > 1 else category_source
    else:
        categories = category_source

    num_reviews = 0
    review_match = re.search(r'(\d+)\s+reviews', page_text, re.IGNORECASE)
    if review_match:
        num_reviews = int(review_match.group(1))

    star_rating = extract_star_rating(soup)

    return {
        'url': book_url, 'Title': title, 'Category_Source': category_source, 'Categories': categories,
        'Authors': authors, 'Price NIS': price_nis, 'Price USD': price_usd, 'Year': year,
        'Synopsis': synopsis, 'Synopsis Length': len(synopsis), 'StarRating': star_rating,
        'NumberOfReviews': num_reviews, 'Language': language, 'Format': format_book,
        'Dimensions': dim_numbers, 'Dimensions unit': dim_unit, 'Weight': weight_num,
        'Weight Unit': weight_unit, 'ISBN': isbn
    }


def cast_numeric(all_books):
    logger.info("Casting data types...")
    df_books = pd.DataFrame(all_books)
    cols = ['Price NIS', 'Price USD', 'Year', 'Synopsis Length', 'StarRating']
    for col in cols:
        if col in df_books.columns:
            df_books[col] = pd.to_numeric(df_books[col], errors='coerce')
    if 'NumberOfReviews' in df_books.columns:
        df_books['NumberOfReviews'] = pd.to_numeric(df_books['NumberOfReviews'], errors='coerce').fillna(0).astype(int)
    return df_books


def file_export(df_books):
    logger.info("Exporting results...")
    os.makedirs("output", exist_ok=True)
    df_books.to_csv("output/books_raw.csv", index=False, encoding="utf-8-sig")
    
    records = []
    for i, row in df_books.iterrows():
        clean_record = {k: v for k, v in row.to_dict().items() if pd.notnull(v) and v != "None"}
        clean_record['id'] = str(i + 1)
        records.append(clean_record)

    with open("output/books_raw.json", "w", encoding="utf-8") as f:
        json.dump({"records": {"record": records}}, f, indent=4, ensure_ascii=False)


def preview_and_sort(df_books):
    logger.info("Generating previews...")
    df_books.head(10).to_csv("output/books_before_sort.csv", index=False, encoding="utf-8-sig")
    df_sorted = df_books.sort_values(by="Title", ascending=True)
    df_sorted.head(10).to_csv("output/books_after_sort.csv", index=False, encoding="utf-8-sig")
    return df_sorted


def process_data(df_books):
    logger.info("Adding derived features...")
    if 'Price NIS' in df_books.columns:
        median_price = df_books['Price NIS'].median()
        df_books['IsExpensive'] = (df_books['Price NIS'] > median_price).astype(int)
    
    if 'Authors' in df_books.columns:
        df_books['NumberOfAuthors'] = df_books['Authors'].apply(
            lambda x: len([a for a in str(x).split(',') if a.strip()]) if pd.notnull(x) and x != "None" else 0
        )

    df_books.to_csv("output/books_processed.csv", index=False, encoding="utf-8-sig")
    return df_books


def calculate_summary_statistics(df_books):
    logger.info("Calculating summary statistics...")
    cols = ['Price USD', 'Year', 'StarRating', 'NumberOfReviews', 'NumberOfAuthors']
    summary_data = {}
    for col in cols:
        if col in df_books.columns:
            valid = pd.to_numeric(df_books[col], errors='coerce').dropna()
            if not valid.empty:
                summary_data[col] = {'mean': valid.mean(), 'std': valid.std(), 'min': valid.min(), 'max': valid.max(), 'median': valid.median()}

    df_summary = pd.DataFrame(summary_data).T
    df_summary['total_rows'] = len(df_books)
    df_summary.to_csv("output/books_summary.csv", index=True, index_label="Column", encoding="utf-8-sig")
    return df_summary


if __name__ == "__main__":
    logger.info("=== STARTING APPLICATION EXECUTION ===")
    try:
        data = crawl_bookdelivery()
        if data:
            df = cast_numeric(data)
            file_export(df)
            df = preview_and_sort(df)
            df = process_data(df)
            calculate_summary_statistics(df)
            logger.info("=== APPLICATION FINISHED SUCCESSFULLY ===")
        else:
            logger.warning("Application finished with NO data collected.")
    except Exception as e:
        logger.critical(f"UNHANDLED APPLICATION EXCEPTION: {e}", exc_info=True)
