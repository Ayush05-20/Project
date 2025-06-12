import time
import random
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

def human_delay(a=2, b=5):
    """Random delay to simulate human browsing"""
    time.sleep(random.uniform(a, b))

def create_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Run in background
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    return webdriver.Chrome(options=chrome_options)

def search_jobs(keyword):
    driver = create_driver()

    url = f"https://www.linkedin.com/jobs/search/?keywords={keyword.replace(' ', '%20')}&location=Worldwide"
    driver.get(url)

    human_delay(3, 6)

    # Scroll to load jobs
    for _ in range(3):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        human_delay()

    soup = BeautifulSoup(driver.page_source, 'html.parser')
    job_cards = soup.find_all('li', class_='jobs-search-results__list-item')

    jobs = []

    for job_card in job_cards[:5]:  # Limit to 5 jobs for demo
        try:
            job_link = job_card.find('a', class_='base-card__full-link')['href']
            driver.get(job_link)
            human_delay(4, 8)

            job_soup = BeautifulSoup(driver.page_source, 'html.parser')

            title = job_soup.find('h1').text.strip()
            company = job_soup.find('a', class_='topcard__org-name-link').text.strip() if job_soup.find('a', class_='topcard__org-name-link') else "N/A"
            location = job_soup.find('span', class_='topcard__flavor topcard__flavor--bullet').text.strip()
            description = job_soup.find('div', class_='show-more-less-html__markup').text.strip()

            jobs.append({
                'title': title,
                'company': company,
                'location': location,
                'description': description
            })

        except Exception as e:
            print("Error scraping job:", e)
            continue

    driver.quit()
    return jobs
if __name__ == "__main__":
    keyword = input("Enter job keyword: ")  # e.g., 'Data Scientist'
    results = search_jobs(keyword)

    for job in results:
        print("\n--- Job Found ---")
        print("Title:", job['title'])
        print("Company:", job['company'])
        print("Location:", job['location'])
        print("Description Snippet:", job['description'][:300], "...")