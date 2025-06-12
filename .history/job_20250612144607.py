import requests
from bs4 import BeautifulSoup
import time
import random
import csv

BASE_URL = "https://www.jobsnepal.com"
CATEGORY = "information-technology"  # Change to another category if needed
SEARCH_URL = f"{BASE_URL}/job-category/{CATEGORY}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/114.0.0.0 Safari/537.36"
}

def human_delay():
    time.sleep(random.uniform(1.5, 3.5))

def get_job_links():
    print(f"Visiting {SEARCH_URL}...")
    try:
        response = requests.get(SEARCH_URL, headers=HEADERS, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"Failed to load job list: {e}")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    jobs = soup.select('div.job-container div.job-title a')
    job_links = [BASE_URL + job['href'] for job in jobs[:5] if job.get('href')]
    return job_links

def get_job_details(url):
    human_delay()
    try:
        print(f"Fetching job details from {url}")
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        title = soup.select_one('h1.job-title')
        description = soup.select_one('div.job-desc')
        requirements_header = soup.find('h3', string=lambda s: s and "Specification" in s)

        return {
            "title": title.get_text(strip=True) if title else "No title",
            "url": url,
            "description": (description.get_text(strip=True)[:500] + "...") if description else "No description available",
            "requirements": (requirements_header.find_next('div').get_text(strip=True)[:500] + "...") if requirements_header else "No requirements listed"
        }

    except Exception as e:
        print(f"Failed to fetch job details from {url}: {e}")
        return {
            "title": "Error fetching job",
            "url": url,
            "description": "N/A",
            "requirements": "N/A"
        }

def export_to_csv(jobs, filename="jobs_nepal.csv"):
    keys = ["title", "url", "description", "requirements"]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(jobs)
    print(f"\n✅ Exported {len(jobs)} jobs to {filename}")

def main():
    print("Starting job scraping with CSV export...\n")
    job_links = get_job_links()

    if not job_links:
        print("No job links found.")
        return

    all_jobs = []
    for job_url in job_links:
        job_data = get_job_details(job_url)
        all_jobs.append(job_data)

    export_to_csv(all_jobs)

if __name__ == "__main__":
    main()
