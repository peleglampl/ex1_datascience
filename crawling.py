import re
from urllib.parse import urljoin
import time
import requests
from bs4 import BeautifulSoup

EXCHANGE_RATE = 3.01
import time
import pandas as pd
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import time

BASE_URL = "https://www.bookdelivery.com/il-en/"
MAX_PAGES_PER_CATEGORY = 5
DELAY = 3
already_verified = False
driver = None

def start_driver():
    options = Options()
    options.add_argument("--window-size=1920,1080")
    # options.add_argument("--headless=new")  # עדיף להשאיר כבוי בהתחלה
    return webdriver.Chrome(options=options)


already_verified = False

def get_soup_from_url(url, delay=5):
    global driver, already_verified

    if driver is None:
        driver = start_driver()

    driver.get(url)

    if not already_verified:
        input("Solve the verification in Chrome, then press ENTER here...")
        already_verified = True

    time.sleep(delay)

    html = driver.page_source
    return BeautifulSoup(html, "html.parser")

def get_category_links(home_soup):
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
        category_links[text] = full_url

    return category_links


def get_book_links_from_category_page(category_soup):
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
    all_books = []
    visited_books = set()

    print("Loading homepage...")
    home_soup = get_soup_from_url(BASE_URL)

    categories = get_category_links(home_soup)
    print(f"Found {len(categories)} category links")

    for category_name, category_url in categories.items():
        print(f"\n=== Category: {category_name} ===")

        for page_num in range(1, MAX_PAGES_PER_CATEGORY + 1):
            page_url = make_page_url(category_url, page_num)
            print(f"Category page {page_num}: {page_url}")

            try:
                category_soup = get_soup_from_url(page_url)
            except Exception as e:
                print(f"Failed category page: {e}")
                break

            book_links = get_book_links_from_category_page(category_soup)

            if not book_links:
                print("No books found on this page. Moving to next category.")
                break

            print(f"Found {len(book_links)} books")

            for book_url in book_links:
                if book_url in visited_books:
                    continue

                visited_books.add(book_url)

                try:
                    print(f"  Crawling book: {book_url}")
                    book_soup = get_soup_from_url(book_url)

                    book_data = get_book_data_from_soup(
                        book_soup,
                        category_source=category_name,
                        book_url=book_url
                    )

                    all_books.append(book_data)

                except Exception as e:
                    print(f"  Failed book: {e}")

                time.sleep(DELAY)

            time.sleep(DELAY)

    df = pd.DataFrame(all_books)
    df.to_csv("books_dataset.csv", index=False, encoding="utf-8-sig")

    print(f"\nDone. Saved {len(df)} books to books_dataset.csv")



def get_book_data_from_soup(soup, category_source, book_url="local file"):
    page_text = soup.get_text(" ", strip=True)

    # -------- TITLE --------
    title = soup.find('h1').get_text(strip=True) if soup.find('h1') else "None"

    # -------- AUTHORS --------
    authors_elements = soup.find_all('a', class_='font-color-bl link-underline')
    authors = ", ".join([a.get_text(strip=True) for a in authors_elements])

    # -------- PRICE --------
    price_nis = 0.0
    price_usd = 0.0

    prices = [float(p) for p in re.findall(r"₪\s*([0-9]+(?:\.[0-9]+)?)", page_text)]

    book_prices = [p for p in prices if p > 40]

    if book_prices:
        price_nis = min(book_prices)
        price_usd = round(price_nis / EXCHANGE_RATE, 2)

    # -------- METADATA BLOCK --------
    meta_block = ""

    match = re.search(
        r"Type\s+Physical Book(.+?)ISBN13\s+\d+",
        page_text,
        re.IGNORECASE
    )

    if match:
        meta_block = match.group(1)

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
    # isbn = extract_between_labels(meta_block, "ISBN13", labels)
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

    # -------- RETURN --------
    return {
        'Title': title,
        'Category_Source': category_source,
        'Categories': "",
        'Authors': authors,
        'Price NIS': price_nis,
        'Price USD': price_usd,
        'Year': year,
        'Synopsis': synopsis,
        'Synopsis Length': len(synopsis),
        'StarRating': "None",
        'NumberOfReviews': 0,
        'Language': language,
        'Format': format_book,
        'Dimensions': dim_numbers,
        'Dimensions unit': dim_unit,
        'Weight': weight_num,
        'Weight Unit': weight_unit,
        'ISBN': isbn
    }


def debug_homepage_links():
    soup = get_soup_from_url(BASE_URL)

    print("PAGE TITLE:", soup.title.get_text(strip=True) if soup.title else "NO TITLE")
    print("TEXT SAMPLE:")
    print(soup.get_text(" ", strip=True)[:1000])

    print("\nALL LINKS:")
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = a["href"]
        print(text, "=>", urljoin(BASE_URL, href))


def debug_homepage_links():
    soup = get_soup_from_url(BASE_URL)

    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = a["href"]
        full_url = urljoin(BASE_URL, href)

        if "bookdelivery.com/il-en/" in full_url:
            print(text, "=>", full_url)

# -------- TEST LIMITS (DELETE LATER) --------
MAX_TEST_CATEGORIES = 2
MAX_BOOKS_PER_CATEGORY = 2


def crawl_bookdelivery_test():
    all_books = []
    visited_books = set()

    print("Loading homepage...")
    home_soup = get_soup_from_url(BASE_URL)

    categories = get_category_links(home_soup)
    print(f"Found {len(categories)} category links")

    # 🔵 LIMIT TO FIRST N CATEGORIES
    for i, (category_name, category_url) in enumerate(categories.items()):
        if i >= MAX_TEST_CATEGORIES:
            break

        print(f"\n=== Category: {category_name} ===")

        for page_num in range(1, MAX_PAGES_PER_CATEGORY + 1):
            page_url = make_page_url(category_url, page_num)
            print(f"Category page {page_num}: {page_url}")

            try:
                category_soup = get_soup_from_url(page_url)
            except Exception as e:
                print(f"Failed category page: {e}")
                break

            book_links = get_book_links_from_category_page(category_soup)

            if not book_links:
                print("No books found on this page. Moving to next category.")
                break

            print(f"Found {len(book_links)} books")

            # 🟢 LIMIT BOOKS PER CATEGORY
            books_counter = 0

            for book_url in book_links:
                if books_counter >= MAX_BOOKS_PER_CATEGORY:
                    break

                if book_url in visited_books:
                    continue

                visited_books.add(book_url)

                try:
                    print(f"  Crawling book: {book_url}")
                    book_soup = get_soup_from_url(book_url)

                    book_data = get_book_data_from_soup(
                        book_soup,
                        category_source=category_name,
                        book_url=book_url
                    )

                    all_books.append(book_data)

                    books_counter += 1

                except Exception as e:
                    print(f"  Failed book: {e}")

                time.sleep(DELAY)

            time.sleep(DELAY)

    df = pd.DataFrame(all_books)
    df.to_csv("books_dataset_test.csv", index=False, encoding="utf-8-sig")

    print(f"\nDone. Saved {len(df)} books to books_dataset_test.csv")

if __name__ == "__main__":

    # crawl_bookdelivery_test()
    crawl_bookdelivery()

    input("Press ENTER to finish...")

