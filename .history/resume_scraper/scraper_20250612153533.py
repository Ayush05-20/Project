# scraper.py
import logging
import time
import random
from typing import List, Dict, Optional
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import re
from selenium.webdriver.chrome.service import Service
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_webdriver() -> webdriver.Chrome:
    """
    Configures and returns a Chrome WebDriver instance.
    Includes options for headless mode, anti-detection, and performance.
    """
    options = Options()
    options.add_argument("--headless=new")  # Use new headless mode
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"user-agent={random_user_agent()}")
    
    # Enhanced anti-bot detection measures
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    # Additional anti-detection measures
    options.add_argument("--lang=en-US,en;q=0.9")
    options.add_argument("--disable-notifications")
    options.add_argument("--incognito")
    
    # Add WebGL support
    options.add_argument("--use-gl=desktop")
    options.add_argument("--use-angle=default")
    
    # Disable images for faster loading
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.notifications": 2,
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False
    }
    options.add_experimental_option("prefs", prefs)
    
    # Add path to chromedriver
    service = Service(executable_path="/Users/ayush/CVisionary-AI Based Resume Screener With Job Matching/chromedriver")

    driver = webdriver.Chrome(options=options)
    
    # Execute CDP commands to modify navigator.webdriver flag
    driver.execute_cdp_cmd('Network.setUserAgentOverride', {"userAgent": random_user_agent()})
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        """
    })
    
    return driver


def random_user_agent():
    """Returns a random common user agent string."""
    agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.1 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/122.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ]
    return random.choice(agents)


def scroll_to_end_of_linkedin_search_results(driver, max_scrolls=3):
    """
    Scrolls down LinkedIn job search results page to load more jobs.
    Uses random delays and human-like behavior.
    """
    last_height = driver.execute_script("return document.body.scrollHeight")
    for i in range(max_scrolls):
        logger.info(f"Scrolling attempt {i+1}/{max_scrolls}")
        
        # Scroll in chunks with random delays
        current_scroll = 0
        target_scroll = last_height
        while current_scroll < target_scroll:
            scroll_amount = random.randint(100, 300)
            driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
            current_scroll += scroll_amount
            time.sleep(random.uniform(0.1, 0.3))
            
        time.sleep(random.uniform(2, 4))
        
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            logger.info("Reached end of scrollable content or no new content loaded.")
            break
        last_height = new_height
        
        # Random chance to pause scrolling (simulates human behavior)
        if random.random() < 0.3:
            time.sleep(random.uniform(1, 2))
    
    # Try to click "See more jobs" button if present
    try:
        see_more_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label='See more jobs']"))
        )
        if see_more_button:
            actions = webdriver.ActionChains(driver)
            actions.move_to_element(see_more_button)
            actions.pause(random.uniform(0.5, 1))
            actions.click()
            actions.perform()
            time.sleep(random.uniform(2, 4))
            logger.info("Clicked 'See more jobs' button.")
    except Exception:
        logger.debug("No 'See more jobs' button found or clickable.")


def scrape_job_links_from_search_page(search_url: str) -> List[Dict]:
    """
    Scrapes job titles, companies, locations, and direct job URLs from a LinkedIn job search page.
    """
    driver = None
    job_cards_data = []
    try:
        driver = create_webdriver()
        logger.info(f"Loading LinkedIn search page: {search_url}")
        
        # Add random delays and mouse movements to appear more human-like
        driver.get(search_url)
        time.sleep(random.uniform(3, 5))
        
        # Wait for the job cards to load with increased timeout
        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.job-card-container"))
            )
        except Exception as e:
            logger.warning(f"Timeout waiting for job cards: {e}")
            return []
            
        time.sleep(random.uniform(2, 4))

        # Scroll with random pauses
        scroll_to_end_of_linkedin_search_results(driver)
        
        # Add random mouse movements
        actions = webdriver.ActionChains(driver)
        elements = driver.find_elements(By.CSS_SELECTOR, "div.job-card-container")
        for element in elements[:min(3, len(elements))]:  # Move to first few elements
            actions.move_to_element(element)
            actions.pause(random.uniform(0.5, 1.5))
        actions.perform()
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        job_cards = soup.find_all("div", class_=re.compile(r"job-card-container|job-search-card"))
        
        if not job_cards:
            logger.warning(f"No job cards found on {search_url}")
            return []

        for card in job_cards:
            try:
                title_elem = card.find("h3", class_="base-search-card__title")
                company_elem = card.find("h4", class_="base-search-card__subtitle")
                location_elem = card.find("span", class_="job-search-card__location")
                
                job_link_elem = card.find("a", class_="base-card__full-link") 
                if not job_link_elem:
                    job_link_elem = card.find("a", class_="job-card-container__link")

                job_url = job_link_elem['href'].split('?')[0] if job_link_elem else None

                if job_url and job_url.startswith("https://www.linkedin.com/jobs/view/"):
                    card_data = {
                        "title": title_elem.get_text(strip=True) if title_elem else "N/A",
                        "company": company_elem.get_text(strip=True) if company_elem else "N/A",
                        "location": location_elem.get_text(strip=True) if location_elem else "N/A",
                        "url": job_url
                    }
                    job_cards_data.append(card_data)
                    
                    # Add random delay between processing cards
                    time.sleep(random.uniform(0.2, 0.5))
            except Exception as e:
                logger.warning(f"Error parsing a job card: {e}")
                continue

        logger.info(f"Successfully scraped {len(job_cards_data)} job links.")
        return job_cards_data

    except Exception as e:
        logger.error(f"Error scraping LinkedIn search page {search_url}: {e}")
        return []
    finally:
        if driver:
            driver.quit()


def scrape_detailed_job_description(job_url: str) -> Optional[str]:
    """
    Scrapes the full job description text from an individual LinkedIn job posting page.
    """
    driver = None
    try:
        driver = create_webdriver()
        logger.info(f"Loading detailed job page: {job_url}")
        driver.get(job_url)

        # Wait for the main job description content to be present
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.description__text"))
        )
        time.sleep(random.uniform(2, 4)) # Allow content to fully render

        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        # Find the main job description element
        description_div = soup.find("div", class_="description__text")
        
        if description_div:
            # Extract text, remove any "Show more" buttons if present
            for span in description_div.find_all("span", class_="show-more-less-html__button"):
                span.decompose() # Remove the button from the soup
            
            full_description = description_div.get_text(separator="\n", strip=True)
            logger.info(f"Successfully scraped detailed description (length: {len(full_description)} chars) for {job_url}")
            return full_description
        else:
            logger.warning(f"Could not find job description div for {job_url}")
            # Try to get the whole body text as a fallback if description div not found
            body = soup.body
            if body:
                return body.get_text(separator="\n", strip=True)
            return None # No useful content found
    except Exception as e:
        logger.error(f"Error scraping detailed job description from {job_url}: {e}")
        return None
    finally:
        if driver:
            driver.quit()


def clean_body_content(html: str) -> str:
    """Cleans general HTML body content, stripping scripts, styles, etc."""
    soup = BeautifulSoup(html, "html.parser")
    # Remove script and style elements
    for script_or_style in soup(["script", "style"]):
        script_or_style.decompose()
    
    body = soup.body
    if body:
        text = body.get_text(separator="\n", strip=True)
        # Remove multiple spaces and newlines
        text = re.sub(r'\n+', '\n', text)
        text = re.sub(r' +', ' ', text)
        return text
    return soup.get_text(separator="\n", strip=True)

