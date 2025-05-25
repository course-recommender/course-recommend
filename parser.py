import time
import csv
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service

import pandas as pd
from constants import SOFTWARE_KEYWORDS, CATEGORY_IDS

CHROME_DRIVER_PATH = r"C:\Users\LEGION\chromedriver.exe"


def extract_software_from_text(text):
    return [
        kw
        for kw in SOFTWARE_KEYWORDS
        if re.search(r"\b" + re.escape(kw) + r"\b", text, re.IGNORECASE)
    ]


def setup_driver():
    options = Options()
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    )
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service(CHROME_DRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)

    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
            Object.defineProperty(navigator, 'webdriver', {
              get: () => undefined
            })
        """
        },
    )

    driver.maximize_window()
    return driver


def load_courses_with_virtual_scroll(
    driver, category_id, max_scrolls=50, early_stop_threshold=3
):
    tried_urls = [
        f"https://stepik.org/catalog/meta/{category_id}",
        f"https://stepik.org/catalog/{category_id}",
    ]

    course_links = set()
    for base_url in tried_urls:
        driver.get(base_url)

        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "a.course-card__title")
                )
            )
        except:
            print(f"⚠️ No courses found on {base_url}")
            continue

        scroll_pause = 2
        no_new_courses_count = 0
        last_count = 0

        for scroll_count in range(max_scrolls):
            cards = driver.find_elements(By.CSS_SELECTOR, "a.course-card__title")
            current_count = 0

            for card in cards:
                href = card.get_attribute("href")
                if href and href not in course_links:
                    course_links.add(href)
                    current_count += 1

            print(
                f"[Scroll {scroll_count+1}] New: {current_count} | Total: {len(course_links)}"
            )

            if current_count == 0:
                no_new_courses_count += 1
            else:
                no_new_courses_count = 0

            if no_new_courses_count >= early_stop_threshold or len(course_links) >= 20:
                print("🛑 Stopping scroll: no new courses or only 1-page content")
                break

            driver.execute_script("window.scrollBy(0, window.innerHeight);")
            time.sleep(scroll_pause)

        if course_links:
            break

    print(f"✅ Total unique courses collected: {len(course_links)}")
    return list(course_links)


def parse_course(driver, url, category_name):
    driver.get(url)
    time.sleep(3)

    print(f"Debug: Accessing course: {url}")
    print("Current URL:", driver.current_url)
    print("Page Source (first 1000 chars):", driver.page_source[:50])

    def safe_get(selector):
        try:
            return driver.find_element(By.CSS_SELECTOR, selector).text.strip()
        except:
            return ""

    def safe_get_attr(selector, attr):
        try:
            return driver.find_element(By.CSS_SELECTOR, selector).get_attribute(attr)
        except:
            return ""

    course_data = {
        "course_name": safe_get("body > main > section.course-promo__head h1"),
        "category": category_name,
        "software": "",
        "certificate": "",
        "teacher": "",
        "course_level": "",
        "course_rating": "",
        "hours_per_week": "",
        "course_link": url,
        "price": "",
    }

    cert_elem = driver.find_elements(By.CSS_SELECTOR, 'div[data-type="certificate"]')
    course_data["certificate"] = cert_elem[0].text.strip() if cert_elem else "No"

    instructors = driver.find_elements(
        By.CSS_SELECTOR,
        "section[data-qa='course-promo__instructors'] div.course-promo__instructor a.author-widget__name",
    )

    teacher_names = [
        instructor.text.strip() for instructor in instructors if instructor.text.strip()
    ]

    if teacher_names:
        course_data["teacher"] = ", ".join(teacher_names)
    else:
        course_data["teacher"] = "No instructor found"

    course_data["course_level"] = safe_get('div[data-type="difficulty"]')

    course_data["course_rating"] = safe_get("span.course-promo-summary__average")

    course_data["hours_per_week"] = safe_get('div[data-type="workload"]')

    def extract_price(driver):
        def get_price_from_selector(selector):
            try:
                price_container = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                price_text = price_container.text.strip()

                if "Бесплатно" in price_text:
                    return 0

                cleaned_price = re.sub(r"\D", "", price_text)
                if cleaned_price:
                    return int(cleaned_price)
                else:
                    return "Price format error"
            except Exception as e:
                print(f"Error extracting price: {e}")
                return "Price Not Available"

        price = get_price_from_selector(
            "div.course-promo-enrollment__price-container > span > span.display-price__price_default > span"
        )

        if price == "Price Not Available":
            price = get_price_from_selector(
                "div.course-promo-enrollment__price-container > span > span.display-price__price_discount > span"
            )

        return price

    course_data["price"] = extract_price(driver)

    try:
        toc_container = driver.find_element(
            By.CSS_SELECTOR, "div.course-toc-sections.toc-promo__sections"
        )
        all_text_elements = toc_container.find_elements(
            By.CSS_SELECTOR,
            ".toc-promo__section-widget-title, .toc-promo-lesson__title",
        )

        full_text = " ".join([el.text for el in all_text_elements if el.text.strip()])
        software_found = extract_software_from_text(full_text)
        course_data["software"] = ", ".join(software_found)
    except Exception as e:
        print(f"⚠️ Failed to extract syllabus/software info: {e}")
        course_data["software"] = ""

    return course_data


def get_category_name(driver, category_id):
    tried_urls = [
        f"https://stepik.org/catalog/meta/{category_id}",
        f"https://stepik.org/catalog/{category_id}",
    ]

    for url in tried_urls:
        driver.get(url)
        time.sleep(3)
        print(f"Debug: Accessing category: {category_id} via {url}")
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (
                        By.CSS_SELECTOR,
                        "body > main > div.marco-layout.catalog-w > header > h1",
                    )
                )
            )
            return driver.find_element(
                By.CSS_SELECTOR,
                "body > main > div.marco-layout.catalog-w > header > h1",
            ).text.strip()
        except Exception as e:
            print(f"⚠️ Failed on {url}: {e}")
            continue

    return f"Category {category_id}"


def main():
    driver = setup_driver()
    all_courses = []

    for category_id in CATEGORY_IDS:
        try:
            category_name = get_category_name(driver, category_id)
            print(f"📦 Category {category_id}: {category_name}")
        except Exception as e:
            print(f"❌ Failed to get category name for ID {category_id}: {e}")
            category_name = f"Category {category_id}"

        course_links = load_courses_with_virtual_scroll(driver, category_id)
        print(f"🔗 Found {len(course_links)} courses")

        for link in course_links:
            print(f"➡️ Parsing course in {category_name}")
            course_data = parse_course(driver, link, category_name)
            all_courses.append(course_data)

    driver.quit()
    print("💾 Saving to courses.csv...")
    df = pd.DataFrame(all_courses)
    df.to_csv("courses-2.csv", index=False)
    print("✅ Done! Saved all courses.")


if __name__ == "__main__":
    main()
