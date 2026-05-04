import math
import re
import logging
from logger_config import logger

EXCHANGE_RATE = 3.01
import pandas as pd
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import time
import os
import json

BASE_URL = "https://www.bookdelivery.com/il-en/"
MAX_PAGES_PER_CATEGORY = 5
DELAY = 5
already_verified = False
driver = None


def start_driver():
    logger.debug("Starting Chrome driver options setup")
    options = Options()
    options.add_argument("--window-size=1920,1080")
    # options.add_argument("--headless=new")  # עדיף להשאיר כבוי בהתחלה
    logger.info("Chrome driver started")
    return webdriver.Chrome(options=options)


def get_soup_from_url(url, delay=5):
    global driver, already_verified

    logger.debug(f"Fetching URL: {url}")
    if driver is None:
        logger.info("Driver is None, starting a new driver")
        driver = start_driver()

    try:
        driver.get(url)
    except Exception as e:
        logger.error(f"Error loading URL {url}: {e}")
        raise

    if not already_verified:
        logger.warning("Manual verification required in Chrome")
        input("Solve the verification in Chrome, then press ENTER here...")
        already_verified = True

    logger.debug(f"Waiting for {delay} seconds delay")
    time.sleep(delay)

    html = driver.page_source
    logger.debug(f"Page source retrieved for {url}")
    return BeautifulSoup(html, "html.parser")


def get_category_links(home_soup):
    logger.info("Extracting category links from homepage")
    category_links = {}

    for a in home_soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = a["href"]
        full_url = urljoin(BASE_URL, href)

        if not text:
            continue

        # real top-level category pages
        if not full_url.startswith("https://www.bookdelivery.com/il-en/books/"):
            continue

        # avoid duplicates
        if text in category_links:
            logger.debug(f"Skipping duplicate category link: {text}")
            continue
            
        category_links[text] = full_url
        logger.debug(f"Found category: {text} -> {full_url}")

    logger.info(f"Total categories found: {len(category_links)}")
    return category_links


def get_book_links_from_category_page(category_soup):
    logger.info("Extracting book links from category page")
    book_links = set()

    for a in category_soup.find_all("a", href=True):
        href = a["href"]
        full_url = urljoin(BASE_URL, href)

        if "/book-" in full_url and "/p/" in full_url:
            book_links.add(full_url)

    logger.debug(f"Found {len(book_links)} unique book links on page")
    return list(book_links)


def make_page_url(category_url, page_num):
    if page_num == 1:
        return category_url

    separator = "&" if "?" in category_url else "?"
    url = f"{category_url}{separator}page={page_num}"
    logger.debug(f"Generated page URL: {url}")
    return url


def crawl_bookdelivery():
    global driver
    all_books = []
    visited_books = set()

    logger.info(f"Starting crawl of {BASE_URL}")
    ####### ADDED ######
    try:
        home_soup = get_soup_from_url(BASE_URL)
    except Exception as e:
        logger.critical(f"Failed to load homepage: {e}", exc_info=True)
        return

    categories = get_category_links(home_soup)

    for category_name, category_url in categories.items():
        logger.info(f"Processing category: {category_name}")

        ##################### ADDED #####################
        #To see when we finish all pages
        previous_page_books = set()

        for page_num in range(1, MAX_PAGES_PER_CATEGORY + 1):
            page_url = make_page_url(category_url, page_num)
            logger.info(f"Scanning page {page_num} of {category_name}")

            try:
                category_soup = get_soup_from_url(page_url)
            except Exception as e:
                logger.error(f"Failed to load category page {page_url}: {e}")
                break

            book_links = get_book_links_from_category_page(category_soup)

            if not book_links:
                logger.info(f"No books found on page {page_num}. Moving to next category.")
                break

            current_page_books = set(book_links)
            if current_page_books == previous_page_books:
                logger.info("Reached the end of pagination (duplicate content). Moving to next category.")
                break

            previous_page_books = current_page_books

            logger.info(f"Found {len(book_links)} books on page {page_num}")

            for book_url in book_links:
                if book_url in visited_books:
                    logger.debug(f"Skipping already visited book: {book_url}")
                    continue

                visited_books.add(book_url)

                try:
                    logger.info(f"Crawling book: {book_url}")
                    book_soup = get_soup_from_url(book_url)

                    book_data = get_book_data_from_soup(
                        book_soup,
                        category_source=category_name,
                        book_url=book_url
                    )

                    all_books.append(book_data)
                    logger.debug(f"Successfully data-extracted for: {book_url}")

                except Exception as e:
                    logger.error(f"Failed to crawl book {book_url}: {e}")

                time.sleep(DELAY)

            time.sleep(DELAY)
            
    if driver is not None:
        logger.info("Closing driver")
        driver.quit()
        driver = None

    logger.info(f"Crawling finished. Total books fetched: {len(all_books)}")
    return all_books


def extract_star_rating(soup):
    logger.debug("Extracting star rating")
    rating_bars = soup.find_all('div', class_='rating-bar')

    if not rating_bars:
        logger.debug("No rating bars found")
        return "None"

    total_stars = 0
    total_votes = 0

    for bar in rating_bars:
        try:
            star_label = bar.find('span', class_='star-label')
            vote_label = bar.find('span', class_='vote-count')
            
            if not star_label or not vote_label:
                continue
                
            star_text = star_label.get_text(strip=True)
            vote_text = vote_label.get_text(strip=True)

            stars = int(re.search(r'\d+', star_text).group())
            votes = int(re.search(r'\d+', vote_text).group())

            total_stars += stars * votes
            total_votes += votes
        except (AttributeError, TypeError, ValueError) as e:
            logger.warning(f"Error parsing rating bar: {e}")
            continue

    if total_votes == 0:
        logger.debug("Total votes is zero")
        return "None"

    raw_rating = total_stars / total_votes
    star_rating = math.ceil(raw_rating * 100) / 100
    logger.debug(f"Calculated star rating: {star_rating}")
    return star_rating


def get_book_data_from_soup(soup, category_source, book_url):
    logger.debug(f"Extracting detailed data for {book_url}")
    page_text = soup.get_text(" ", strip=True)

    # -------- TITLE --------
    title_h1 = soup.find('h1')
    title = title_h1.get_text(strip=True) if title_h1 else "None"
    if title == "None":
        logger.warning(f"Title not found for book: {book_url}")

    # -------- AUTHORS --------
    authors_elements = soup.find_all('a', class_='font-color-bl link-underline')
    authors = ", ".join([a.get_text(strip=True) for a in authors_elements])
    if not authors:
        logger.debug(f"No authors found for: {title}")

    # -------- PRICE --------
    price_nis = 0.0
    price_usd = 0.0

    prices = [float(p) for p in re.findall(r"₪\s*([0-9]+(?:\.[0-9]+)?)", page_text)]
    book_prices = [p for p in prices if p > 40]

    if book_prices:
        price_nis = min(book_prices)
        price_nis = math.ceil(price_nis * 100) / 100
        price_usd = math.ceil((price_nis / EXCHANGE_RATE) * 100) / 100
    else:
        logger.warning(f"No valid price found for {title}")

    # -------- METADATA BLOCK --------
    meta_block = ""
    match = re.search(
        r"Type\s+Physical Book(.+?)ISBN13\s+\d+",
        page_text,
        re.IGNORECASE
    )

    if match:
        meta_block = match.group(1)
    else:
        logger.debug(f"Metadata block not found for {title}")

    # -------- EXTRACT FUNCTION --------
    def extract_between_labels(block, label, next_labels):
        pattern = label + r"\s+(.+?)\s+(?=" + "|".join(next_labels) + r"|$)"
        match = re.search(pattern, block, re.IGNORECASE)
        return match.group(1).strip() if match else "None"

    labels = [
        "Type", "Author", "Publisher", "Collection", "Year",
        "Language", "Pages", "Format", "Dimensions", "Weight", "ISBN13"
    ]

    year = extract_between_labels(meta_block, "Year", labels)
    language = extract_between_labels(meta_block, "Language", labels)
    format_book = extract_between_labels(meta_block, "Format", labels)
    dim_raw = extract_between_labels(meta_block, "Dimensions", labels)
    weight_raw = extract_between_labels(meta_block, "Weight", labels)
    isbn_match = re.search(r"ISBN13\s+(\d+)", page_text, re.IGNORECASE)
    isbn = isbn_match.group(1) if isbn_match else "None"

    # -------- DIMENSIONS --------
    dim_numbers = ", ".join(re.findall(r'[0-9.]+', dim_raw))
    dim_unit = "cm" if "cm" in dim_raw.lower() else ("inch" if "inch" in dim_raw.lower() else "")

    # -------- WEIGHT --------
    if weight_raw == "None":
        weight_num = ""
        weight_unit = ""
    else:
        weight_num = "".join(re.findall(r'[0-9.]+', weight_raw))
        weight_unit = (
            "pounds" if "pound" in weight_raw.lower()
            else "kg" if "kg" in weight_raw.lower()
            else "gr"
        )

    # -------- SYNOPSIS --------
    synopsis = ""
    syn_match = re.search(
        r"Synopsis\s+(.+?)\s+Translate to english",
        page_text,
        re.IGNORECASE
    )
    if syn_match:
        synopsis = syn_match.group(1).strip()
    else:
        logger.debug(f"Synopsis not found for {title}")

    # ------ Categories ------
    breadcrumb_wrap = soup.find('div', class_='breadcrumb-wrapper')
    if breadcrumb_wrap:
        cat_list = [a.get_text(strip=True) for a in breadcrumb_wrap.find_all('a')]
        categories = ", ".join(cat_list[1:]) if len(cat_list) > 1 else category_source
    else:
        categories = category_source

    # ----- REVIEWS ------
    num_reviews = 0
    review_match = re.search(r'(\d+)\s+reviews', page_text, re.IGNORECASE)
    if review_match:
        num_reviews = int(review_match.group(1))

    star_rating = extract_star_rating(soup)

    return {
        'url': book_url,
        'Title': title,
        'Category_Source': category_source,
        'Categories': categories,
        'Authors': authors,
        'Price NIS': price_nis,
        'Price USD': price_usd,
        'Year': year,
        'Synopsis': synopsis,
        'Synopsis Length': len(synopsis),
        'StarRating': star_rating,
        'NumberOfReviews': num_reviews,
        'Language': language,
        'Format': format_book,
        'Dimensions': dim_numbers,
        'Dimensions unit': dim_unit,
        'Weight': weight_num,
        'Weight Unit': weight_unit,
        'ISBN': isbn
    }


def cast_numeric(all_books):
    logger.info("Casting data types to numeric")
    df_books = pd.DataFrame(all_books)

    cols_to_convert = ['Price NIS', 'Price USD', 'Year', 'Synopsis Length', 'StarRating']
    for col in cols_to_convert:
        if col in df_books.columns:
            logger.debug(f"Converting column {col} to numeric")
            df_books[col] = pd.to_numeric(df_books[col], errors='coerce')

    if 'NumberOfReviews' in df_books.columns:
        logger.debug("Converting NumberOfReviews to int")
        df_books['NumberOfReviews'] = pd.to_numeric(df_books['NumberOfReviews'],
                                                    errors='coerce').fillna(0).astype(int)
    return df_books


def file_export(df_books):
    logger.info("Exporting data to files")
    os.makedirs("output", exist_ok=True)
    
    csv_path = "output/books_raw.csv"
    logger.info(f"Saving CSV to {csv_path}")
    df_books.to_csv(csv_path, index=False, encoding="utf-8-sig")

    json_path = "output/books_raw.json"
    logger.info(f"Saving JSON to {json_path}")
    records_list = []
    for i, row in df_books.iterrows():
        clean_record = {k: v for k, v in row.to_dict().items() if pd.notnull(v) and v != "None"}
        clean_record['id'] = str(i + 1)
        records_list.append(clean_record)

    json_output = {"records": {"record": records_list}}
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_output, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save JSON: {e}")


def preview_and_sort(df_books):
    logger.info("Sorting data by Title")
    
    df_books.head(10).to_csv("output/books_before_sort.csv", index=False, encoding="utf-8-sig")

    df_sorted = df_books.sort_values(by="Title", ascending=True)
    df_sorted.head(10).to_csv("output/books_after_sort.csv", index=False, encoding="utf-8-sig")
    return df_sorted


def process_data(df_books):
    logger.info("Processing data: adding derived features")
    
    if 'Price NIS' in df_books.columns:
        median_price = df_books['Price NIS'].median()
        logger.debug(f"Median price NIS: {median_price}")
        df_books['IsExpensive'] = (df_books['Price NIS'] > median_price).astype(int)
    else:
        logger.warning("Price NIS column not found, cannot calculate IsExpensive")

    if 'Authors' in df_books.columns:
        df_books['NumberOfAuthors'] = df_books['Authors'].apply(
            lambda x: len([a for a in str(x).split(',') if a.strip()]) if pd.notnull(x) and x != "None" else 0
        )
    else:
        logger.warning("Authors column not found, cannot calculate NumberOfAuthors")

    df_books.to_csv("output/books_processed.csv", index=False, encoding="utf-8-sig")

    records_list = []
    for i, row in df_books.iterrows():
        clean_record = {k: v for k, v in row.to_dict().items() if pd.notnull(v) and v != "None"}
        clean_record['id'] = str(i + 1)
        records_list.append(clean_record)

    json_processed = {"records": {"record": records_list}}
    with open("output/books_processed.json", "w", encoding="utf-8") as f:
        json.dump(json_processed, f, indent=4, ensure_ascii=False)

    df_books.head(10).to_csv("output/books_processed_preview.csv", index=False, encoding="utf-8-sig")
    return df_books


def calculate_summary_statistics(df_books):
    logger.info("Calculating summary statistics")
    columns_to_analyze = [
        'Price USD',
        'Year',
        'StarRating',
        'NumberOfReviews',
        'NumberOfAuthors'
    ]

    summary_data = {}
    total_rows = len(df_books)

    for col in columns_to_analyze:
        if col in df_books.columns:
            valid_series = pd.to_numeric(df_books[col], errors='coerce').dropna()

            if len(valid_series) > 0:
                summary_data[col] = {
                    'mean': valid_series.mean(),
                    'std': valid_series.std(),
                    'min': valid_series.min(),
                    'max': valid_series.max(),
                    'median': valid_series.median()
                }
            else:
                logger.warning(f"No valid data for summary of column: {col}")
                summary_data[col] = {'mean': None, 'std': None, 'min': None, 'max': None, 'median': None}
        else:
            logger.warning(f"Column '{col}' not found for summary.")

    df_summary = pd.DataFrame(summary_data).T
    df_summary['total_rows'] = total_rows

    os.makedirs("output", exist_ok=True)
    df_summary.to_csv("output/books_summary.csv", index=True, index_label="Column", encoding="utf-8-sig")
    logger.info("Summary statistics saved to output/books_summary.csv")

    return df_summary


if __name__ == "__main__":
    logger.info("Script started")
    try:
        book_data_list = crawl_bookdelivery()
        if book_data_list:
            df_books = cast_numeric(book_data_list)
            file_export(df_books)
            df_books = preview_and_sort(df_books)
            df_books = process_data(df_books)
            summary = calculate_summary_statistics(df_books)
            logger.info("Script completed successfully")
        else:
            logger.warning("No book data collected")
    except Exception as e:
        logger.critical(f"Critical error in main execution: {e}", exc_info=True)
