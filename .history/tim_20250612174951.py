import argparse
import time
import random
import json
import urllib.parse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Template for parsing job information
template = (
    "You are tasked with extracting job information from LinkedIn job listings. "
    "From the following HTML content: {dom_content}, please extract job information in JSON format. "
    "Extract the following fields for each job: job_title, company_name, location, job_type, salary (if available), "
    "experience_level, posted_date, job_description_snippet. "
    "Return the data as a JSON array. If no jobs are found, return an empty array []."
)

model = OllamaLLM(model="llama3.2")

class LinkedInJobScraper:
    def __init__(self):
        self.driver = None
        self.wait = None
        self.scraped_jobs = []
        
    def setup_driver(self):
        """Setup Chrome driver with anti-detection measures"""
        logger.info("Setting up Chrome WebDriver with anti-bot detection...")
        
        options = webdriver.ChromeOptions()
        
        # Anti-detection measures
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # User agent rotation
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        ]
        options.add_argument(f"--user-agent={random.choice(user_agents)}")
        
        # Additional options for stealth
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--start-maximized")
        
        # Disable images and CSS for faster loading
        prefs = {
            "profile.managed_default_content_settings.images": 2,
            "profile.default_content_setting_values.notifications": 2,
            "profile.managed_default_content_settings.stylesheets": 2,
        }
        options.add_experimental_option("prefs", prefs)
        
        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
            
            # Execute script to remove webdriver property
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            self.wait = WebDriverWait(self.driver, 10)
            logger.info("WebDriver setup completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to setup WebDriver: {str(e)}")
            return False
    
    def human_like_scroll(self):
        """Simulate human-like scrolling behavior"""
        scroll_pause_time = random.uniform(1, 3)
        
        # Get scroll height
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        
        while True:
            # Scroll down with random speed
            scroll_increment = random.randint(300, 800)
            self.driver.execute_script(f"window.scrollBy(0, {scroll_increment});")
            
            # Wait to load page
            time.sleep(scroll_pause_time)
            
            # Calculate new scroll height and compare with last scroll height
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
    
    def handle_popup_or_login(self):
        """Handle LinkedIn popups and login prompts"""
        try:
            # Check for login popup
            close_buttons = [
                "//button[@aria-label='Dismiss']",
                "//button[contains(@class, 'modal__dismiss')]",
                "//button[contains(text(), 'Skip')]",
                "//button[contains(text(), 'Close')]",
                "//div[contains(@class, 'modal')]//button",
                "//button[@data-tracking-control-name='public_jobs_contextual-sign-in-modal_modal_dismiss']"
            ]
            
            for button_xpath in close_buttons:
                try:
                    close_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, button_xpath)))
                    close_button.click()
                    logger.info("Closed popup/modal")
                    time.sleep(random.uniform(1, 2))
                    break
                except TimeoutException:
                    continue
                    
        except Exception as e:
            logger.debug(f"No popup to handle: {str(e)}")
    
    def build_linkedin_url(self, job_title, location, experience_level="", job_type=""):
        """Build LinkedIn jobs URL with parameters"""
        base_url = "https://www.linkedin.com/jobs/search"
        
        params = {
            'keywords': job_title,
            'location': location,
            'trk': 'public_jobs_jobs-search-bar_search-submit',
            'position': '1',
            'pageNum': '0'
        }
        
        if experience_level:
            # Map experience levels to LinkedIn's format
            experience_map = {
                'entry': '2',
                'associate': '3',
                'mid': '4',
                'senior': '5',
                'executive': '6'
            }
            if experience_level.lower() in experience_map:
                params['f_E'] = experience_map[experience_level.lower()]
        
        if job_type:
            # Map job types to LinkedIn's format
            job_type_map = {
                'full-time': 'F',
                'part-time': 'P',
                'contract': 'C',
                'temporary': 'T',
                'internship': 'I'
            }
            if job_type.lower() in job_type_map:
                params['f_JT'] = job_type_map[job_type.lower()]
        
        return f"{base_url}?{urllib.parse.urlencode(params)}"
    
    def scrape_jobs_page(self, url):
        """Scrape jobs from a single page"""
        try:
            logger.info(f"Navigating to: {url}")
            self.driver.get(url)
            
            # Random delay to mimic human behavior
            time.sleep(random.uniform(3, 7))
            
            # Handle any popups
            self.handle_popup_or_login()
            
            # Wait for job listings to load
            try:
                self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "jobs-search__results-list")))
            except TimeoutException:
                logger.warning("Jobs list not found, trying alternative selectors")
                try:
                    self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "job-result-card")))
                except TimeoutException:
                    logger.error("No job listings found on page")
                    return []
            
            # Scroll to load more jobs
            logger.info("Scrolling to load all jobs...")
            self.human_like_scroll()
            
            # Get page source
            html_content = self.driver.page_source
            return self.extract_jobs_from_html(html_content)
            
        except Exception as e:
            logger.error(f"Error scraping page: {str(e)}")
            return []
    
    def extract_jobs_from_html(self, html_content):
        """Extract job information from HTML content"""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find job cards
        job_cards = soup.find_all(['div'], class_=lambda x: x and ('job-result-card' in x or 'jobs-search-results__list-item' in x))
        
        if not job_cards:
            # Try alternative selectors
            job_cards = soup.find_all(['li'], class_=lambda x: x and 'jobs-search-results__list-item' in x)
        
        jobs = []
        for card in job_cards:
            try:
                job_data = self.parse_job_card(card)
                if job_data:
                    jobs.append(job_data)
            except Exception as e:
                logger.debug(f"Error parsing job card: {str(e)}")
                continue
        
        logger.info(f"Extracted {len(jobs)} jobs from page")
        return jobs
    
    def parse_job_card(self, card):
        """Parse individual job card"""
        try:
            # Extract job title
            title_elem = card.find(['h3', 'h4'], class_=lambda x: x and 'job-result-card__title' in x)
            if not title_elem:
                title_elem = card.find(['a'], class_=lambda x: x and 'job-result-card__title-link' in x)
            
            job_title = title_elem.get_text(strip=True) if title_elem else "N/A"
            
            # Extract company name
            company_elem = card.find(['h4', 'a'], class_=lambda x: x and 'job-result-card__subtitle' in x)
            if not company_elem:
                company_elem = card.find(['span'], class_=lambda x: x and 'job-result-card__subtitle-link' in x)
            
            company_name = company_elem.get_text(strip=True) if company_elem else "N/A"
            
            # Extract location
            location_elem = card.find(['span'], class_=lambda x: x and 'job-result-card__location' in x)
            location = location_elem.get_text(strip=True) if location_elem else "N/A"
            
            # Extract job link
            link_elem = card.find('a', href=True)
            job_link = link_elem['href'] if link_elem else "N/A"
            if job_link != "N/A" and not job_link.startswith('http'):
                job_link = f"https://www.linkedin.com{job_link}"
            
            # Extract additional info
            metadata = card.find(['span'], class_=lambda x: x and 'job-result-card__listdate' in x)
            posted_date = metadata.get_text(strip=True) if metadata else "N/A"
            
            return {
                'job_title': job_title,
                'company_name': company_name,
                'location': location,
                'posted_date': posted_date,
                'job_link': job_link
            }
            
        except Exception as e:
            logger.debug(f"Error parsing job card: {str(e)}")
            return None
    
    def get_next_page_url(self, current_url, page_num):
        """Generate next page URL"""
        if '&start=' in current_url:
            # Replace existing start parameter
            import re
            new_url = re.sub(r'&start=\d+', f'&start={page_num * 25}', current_url)
        else:
            # Add start parameter
            new_url = f"{current_url}&start={page_num * 25}"
        
        return new_url
    
    def has_next_page(self):
        """Check if there's a next page available"""
        try:
            # Look for pagination buttons
            next_button = self.driver.find_element(By.XPATH, "//button[@aria-label='Next']")
            return next_button.is_enabled()
        except NoSuchElementException:
            try:
                # Alternative pagination check
                pagination = self.driver.find_element(By.CSS_SELECTOR, ".jobs-search-pagination__button--next")
                return "disabled" not in pagination.get_attribute("class")
            except NoSuchElementException:
                return False
    
    def scrape_multiple_pages(self, job_title, location, max_pages=5, experience_level="", job_type=""):
        """Scrape multiple pages of job listings"""
        if not self.setup_driver():
            return []
        
        try:
            base_url = self.build_linkedin_url(job_title, location, experience_level, job_type)
            all_jobs = []
            
            for page_num in range(max_pages):
                logger.info(f"Scraping page {page_num + 1} of {max_pages}")
                
                if page_num == 0:
                    url = base_url
                else:
                    url = self.get_next_page_url(base_url, page_num)
                
                jobs = self.scrape_jobs_page(url)
                all_jobs.extend(jobs)
                
                # Random delay between pages
                time.sleep(random.uniform(5, 10))
                
                # Check if there's a next page
                if page_num < max_pages - 1 and not self.has_next_page():
                    logger.info("No more pages available")
                    break
            
            logger.info(f"Total jobs scraped: {len(all_jobs)}")
            return all_jobs
            
        except Exception as e:
            logger.error(f"Error during scraping: {str(e)}")
            return []
        finally:
            if self.driver:
                self.driver.quit()
    
    def save_results(self, jobs, filename="linkedin_jobs.json"):
        """Save results to JSON file"""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(jobs, f, indent=2, ensure_ascii=False)
            logger.info(f"Results saved to {filename}")
        except Exception as e:
            logger.error(f"Error saving results: {str(e)}")

def main():
    parser = argparse.ArgumentParser(
        description="LinkedIn Job Scraper - Extract job listings with anti-bot detection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python linkedin_scraper.py "Software Engineer" "San Francisco, CA" --pages 3
  python linkedin_scraper.py "Data Scientist" "Remote" --pages 5 --experience senior
  python linkedin_scraper.py "Marketing Manager" "New York, NY" --job-type full-time --pages 2
        """
    )
    
    parser.add_argument(
        "job_title",
        help="Job title to search for (e.g., 'Software Engineer', 'Data Scientist')"
    )
    
    parser.add_argument(
        "location",
        help="Location to search in (e.g., 'San Francisco, CA', 'Remote', 'United States')"
    )
    
    parser.add_argument(
        "--pages",
        type=int,
        default=3,
        help="Number of pages to scrape (default: 3)"
    )
    
    parser.add_argument(
        "--experience",
        choices=['entry', 'associate', 'mid', 'senior', 'executive'],
        help="Experience level filter"
    )
    
    parser.add_argument(
        "--job-type",
        choices=['full-time', 'part-time', 'contract', 'temporary', 'internship'],
        help="Job type filter"
    )
    
    parser.add_argument(
        "--output",
        default="linkedin_jobs.json",
        help="Output filename (default: linkedin_jobs.json)"
    )
    
    args = parser.parse_args()
    
    logger.info(f"Starting LinkedIn job scraper...")
    logger.info(f"Job Title: {args.job_title}")
    logger.info(f"Location: {args.location}")
    logger.info(f"Pages: {args.pages}")
    
    scraper = LinkedInJobScraper()
    
    try:
        jobs = scraper.scrape_multiple_pages(
            job_title=args.job_title,
            location=args.location,
            max_pages=args.pages,
            experience_level=args.experience or "",
            job_type=args.job_type or ""
        )
        
        if jobs:
            scraper.save_results(jobs, args.output)
            print(f"\nScraping completed! Found {len(jobs)} jobs.")
            print(f"Results saved to: {args.output}")
            
            # Display sample results
            print("\nSample results:")
            for i, job in enumerate(jobs[:3]):
                print(f"\n{i+1}. {job['job_title']}")
                print(f"   Company: {job['company_name']}")
                print(f"   Location: {job['location']}")
                print(f"   Posted: {job['posted_date']}")
        else:
            print("No jobs found. Please check your search criteria.")
            
    except KeyboardInterrupt:
        logger.info("Scraping interrupted by user")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
    finally:
        logger.info("Scraping session ended")

if __name__ == "__main__":
    main()