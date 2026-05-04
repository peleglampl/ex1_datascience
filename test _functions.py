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
# MAX_TEST_CATEGORIES = 1
# MAX_BOOKS_PER_CATEGORY = 10


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


if __name__ == "__main__":
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
