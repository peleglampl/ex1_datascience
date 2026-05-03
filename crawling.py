import re

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
DELAY = 3
already_verified = False
driver = None


def start_driver():
    options = Options()
    options.add_argument("--window-size=1920,1080")
    # options.add_argument("--headless=new")  # עדיף להשאיר כבוי בהתחלה
    return webdriver.Chrome(options=options)


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


def get_book_data_from_soup(soup, category_source):
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

    # ------ Categories ------
    # Look for the breadcrumb navigation or category tags
    breadcrumb_wrap = soup.find('div', class_='breadcrumb-wrapper')
    if breadcrumb_wrap:
        # Get all text from links in the breadcrumb, excluding 'Home'
        cat_list = [a.get_text(strip=True) for a in breadcrumb_wrap.find_all('a')]
        categories = ", ".join(cat_list[1:]) if len(cat_list) > 1 else category_source
    else:
        categories = category_source

    # ----- REVIEWS ------
    # Find the review section
    reviews_text = soup.find('div', class_='rating-count')  # Example class, check actual HTML
    num_reviews = 0
    star_rating = "None"

    # Extracting Number of Reviews
    review_match = re.search(r'(\d+)\s+reviews', page_text, re.IGNORECASE)
    if review_match:
        num_reviews = int(review_match.group(1))

    # Calculating Star Rating (Logic based on "Star Distribution")
    # If the site provides a specific average rating in the meta tags:
    rating_meta = soup.find('meta', itemprop='ratingValue')
    if rating_meta and num_reviews > 0:
        # Rounding up to 2 decimal digits as required[cite: 1]
        star_rating = round(float(rating_meta['content']) + 0.005, 2)

    # -------- RETURN --------
    return {
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


# def debug_homepage_links():
#     soup = get_soup_from_url(BASE_URL)
#
#     print("PAGE TITLE:", soup.title.get_text(strip=True) if soup.title else "NO TITLE")
#     print("TEXT SAMPLE:")
#     print(soup.get_text(" ", strip=True)[:1000])
#
#     print("\nALL LINKS:")
#     for a in soup.find_all("a", href=True):
#         text = a.get_text(" ", strip=True)
#         href = a["href"]
#         print(text, "=>", urljoin(BASE_URL, href))


# def debug_homepage_links():
#     soup = get_soup_from_url(BASE_URL)
#
#     for a in soup.find_all("a", href=True):
#         text = a.get_text(" ", strip=True)
#         href = a["href"]
#         full_url = urljoin(BASE_URL, href)
#
#         if "bookdelivery.com/il-en/" in full_url:
#             print(text, "=>", full_url)

# -------- TEST LIMITS (DELETE LATER) --------
MAX_TEST_CATEGORIES = 1
MAX_BOOKS_PER_CATEGORY = 10


# def crawl_bookdelivery_test():
#     all_books = []
#     visited_books = set()
#
#     print("Loading homepage...")
#     home_soup = get_soup_from_url(BASE_URL)
#
#     categories = get_category_links(home_soup)
#     print(f"Found {len(categories)} category links")
#
#     # 🔵 LIMIT TO FIRST N CATEGORIES
#     for i, (category_name, category_url) in enumerate(categories.items()):
#         if i >= MAX_TEST_CATEGORIES:
#             break
#
#         print(f"\n=== Category: {category_name} ===")
#
#         for page_num in range(1, MAX_PAGES_PER_CATEGORY + 1):
#             page_url = make_page_url(category_url, page_num)
#             print(f"Category page {page_num}: {page_url}")
#
#             try:
#                 category_soup = get_soup_from_url(page_url)
#             except Exception as e:
#                 print(f"Failed category page: {e}")
#                 break
#
#             book_links = get_book_links_from_category_page(category_soup)
#
#             if not book_links:
#                 print("No books found on this page. Moving to next category.")
#                 break
#
#             print(f"Found {len(book_links)} books")
#
#             # 🟢 LIMIT BOOKS PER CATEGORY
#             books_counter = 0
#
#             for book_url in book_links:
#                 if books_counter >= MAX_BOOKS_PER_CATEGORY:
#                     break
#
#                 if book_url in visited_books:
#                     continue
#
#                 visited_books.add(book_url)
#
#                 try:
#                     print(f"  Crawling book: {book_url}")
#                     book_soup = get_soup_from_url(book_url)
#
#                     book_data = get_book_data_from_soup(
#                         book_soup,
#                         category_source=category_name,
#                         book_url=book_url
#                     )
#
#                     all_books.append(book_data)
#
#                     books_counter += 1
#
#                 except Exception as e:
#                     print(f"  Failed book: {e}")
#
#                 time.sleep(DELAY)
#
#             time.sleep(DELAY)
#
#     # df = pd.DataFrame(all_books)
#     # df.to_csv("books_dataset_test.csv", index=False, encoding="utf-8-sig")
#
#     #print(f"\nDone. Saved {len(df)} books to books_dataset_test.csv")
#     return all_books


# Part 2:
# Question 1:
def cast_numeric(all_books):
    # Convert your list of dicts to a DataFrame
    df_books = pd.DataFrame(all_books)

    # Cast numeric fields
    # Price in NIS (2 decimal digits, rounded up)
    df_books['Price NIS'] = pd.to_numeric(df_books['Price NIS'], errors='coerce').apply(lambda x: round(x + 0.005, 2))

    # Price in USD (rounded up)
    df_books['Price USD'] = pd.to_numeric(df_books['Price USD'], errors='coerce').apply(lambda x: round(x + 0.005, 2))

    # Other numeric fields
    df_books['Year'] = pd.to_numeric(df_books['Year'], errors='coerce')
    df_books['Synopsis Length'] = pd.to_numeric(df_books['Synopsis Length'], errors='coerce')
    df_books['NumberOfReviews'] = pd.to_numeric(df_books['NumberOfReviews'], errors='coerce').fillna(0).astype(int)
    return df_books


# Question 2:
def file_export(df_books):
    # Ensure output directory exists
    os.makedirs("output", exist_ok=True)
    # Save CSV
    df_books.to_csv("output/books_raw.csv", index=False, encoding="utf-8-sig")

    # Save JSON with the specific required structure
    # The instruction says: if a field is missing, it should not be in the JSON
    records_list = []
    for i, row in df_books.iterrows():
        # Remove 'None' or NaN values for this specific record
        clean_record = {k: v for k, v in row.to_dict().items() if pd.notnull(v) and v != "None"}
        clean_record['id'] = str(i + 1)  # Adding an ID as shown in the example
        records_list.append(clean_record)

    json_output = {
        "records": {
            "record": records_list
        }
    }

    with open("output/books_raw.json", "w", encoding="utf-8") as f:
        json.dump(json_output, f, indent=4, ensure_ascii=False)


# Question 3:
def preview_and_sort(df_books):
    # Before Sorting
    print("\n--- First 10 rows before sorting ---")
    print(df_books.head(10))
    # Save to output/books_before_sort.csv
    df_books.head(10).to_csv("output/books_before_sort.csv", index=False, encoding="utf-8-sig")

    # Sorted the DataFrame by Title in ascending order
    df_sorted = df_books.sort_values(by="Title", ascending=True)

    print("\nFirst 10 rows after sorting by Title")
    print(df_sorted.head(10))
    # Save to output/books_after_sort.csv
    df_sorted.head(10).to_csv("output/books_after_sort.csv", index=False, encoding="utf-8-sig")
    return df_sorted


# Question 4:
def process_data(df_books):
    # Added IsExpensive
    # Calculate the median of the Price NIS column
    median_price = df_books['Price NIS'].median()
    # Assign 1 if price > median
    df_books['IsExpensive'] = (df_books['Price NIS'] > median_price).astype(int)

    # Added NumberOfAuthors
    # Count names in the comma-separated string and handle "None" or empty
    df_books['NumberOfAuthors'] = df_books['Authors'].apply(
        lambda x: len([a for a in str(x).split(',') if a.strip()]) if pd.notnull(x) and x != "None" else 0
    )

    # Save Processed CSV
    df_books.to_csv("output/books_processed.csv", index=False, encoding="utf-8-sig")

    # Save Processed JSON
    records_list = []
    for i, row in df_books.iterrows():
        clean_record = {k: v for k, v in row.to_dict().items() if pd.notnull(v) and v != "None"}
        clean_record['id'] = str(i + 1)
        records_list.append(clean_record)

    json_processed = {"records": {"record": records_list}}
    with open("output/books_processed.json", "w", encoding="utf-8") as f:
        json.dump(json_processed, f, indent=4, ensure_ascii=False)

    # Save Preview
    print("\n--- First 10 rows after processing ---")
    print(df_books.head(10))
    df_books.head(10).to_csv("output/books_processed_preview.csv", index=False, encoding="utf-8-sig")
    return df_books


# Question 5:
def calculate_summary_statistics(df_books):
    # leaving the columns that need to stay
    columns_to_analyze = [
        'Price USD',
        'Year',
        'StarRating',
        'NumberOfReviews',
        'NumberOfAuthors'
    ]

    # Creating a dictionary
    summary_data = {}
    total_rows = len(df_books)

    for col in columns_to_analyze:
        if col in df_books.columns:
            # change to numeric and ignore non numbers
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
                # If there is no valid word
                summary_data[col] = {
                    'mean': None,
                    'std': None,
                    'min': None,
                    'max': None,
                    'median': None
                }
        else:
            print(f"Warning: Column '{col}' not found in DataFrame.")

    # Conversion to a DataFrame where the index is the column name
    df_summary = pd.DataFrame(summary_data).T

    # Adding a column of the sum of rows in the table
    df_summary['total_rows'] = total_rows

    print(df_summary)

    # save to output
    os.makedirs("output", exist_ok=True)
    df_summary.to_csv("output/books_summary.csv", index=True, index_label="Column", encoding="utf-8-sig")
    print("\nStep 5 Complete: Summary statistics saved to output/books_summary.csv")

    return df_summary


if __name__ == "__main__":
    # book_data_list = crawl_bookdelivery()
    book_data_list = crawl_bookdelivery()
    # book_data_list = crawl_bookdelivery_test()
    if book_data_list:
        # Step 2 & 3: Construction and Sorting[cite: 1]
        df_books = cast_numeric(book_data_list)
        file_export(df_books)
        df_books = preview_and_sort(df_books)

        # Step 4: Data Processing[cite: 1]
        df_books = process_data(df_books)

        # Step 5:
        summary = calculate_summary_statistics(df_books)

        print("\nStep 4 Complete: Derived features added and saved.")
