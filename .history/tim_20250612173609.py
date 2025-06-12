import argparse
import time
import random
import json
import os
from urllib.parse import quote, urljoin
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
import undetected_chromedriver as uc

# Template for parsing
template = (
    "You are tasked with extracting specific information from the following LinkedIn job content: {dom_content}. "
    "Please follow these instructions carefully: \n\n"
    "1. **Extract Information:** Only extract the information that directly matches the provided description: {parse_description}. "
    "2. **No Extra Content:** Do not include any additional text, comments, or explanations in your response. "
    "3. **Empty Response:** If no information matches the description, return an empty string ('')."
    "4. **Direct Data Only:** Your output should contain only the data that is explicitly requested, with no other text."
    "5. **LinkedIn Format:** Focus on job titles, company names, locations, experience levels, and job descriptions."
)

model = OllamaLLM(model="llama3.2")

class LinkedInScraper:
    def __init__(self):
        self.driver = None
        self.wait = None
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0"
        ]
        
    def setup_driver(self):
        """Setup Chrome driver with anti-detection measures"""
        print("Setting up enhanced WebDriver with anti-detection...")
        
        try:
            # Use undetected-chromedriver for better anti-detection
            options = uc.ChromeOptions()
            
            # Basic stealth options
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            
            # Random user agent
            user_agent = random.choice(self.user_agents)
            options.add_argument(f"--user-agent={user_agent}")
            
            # Additional anti-detection measures
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-plugins-discovery")
            options.add_argument("--disable-web-security")
            options.add_argument("--allow-running-insecure-content")
            options.add_argument("--no-first-run")
            options.add_argument("--disable-notifications")
            options.add_argument("--disable-popup-blocking")
            
            # Window size randomization
            window_sizes = ["1920,1080", "1366,768", "1440,900", "1536,864"]
            options.add_argument(f"--window-size={random.choice(window_sizes)}")
            
            # Create driver
            self.driver = uc.Chrome(options=options)
            self.wait = WebDriverWait(self.driver, 20)
            
            # Execute stealth scripts
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            self.driver.execute_cdp_cmd('Network.setUserAgentOverride', {
                "userAgent": user_agent,
                "acceptLanguage": "en-US,en;q=0.9",
                "platform": "Win32"
            })
            
            return True
            
        except Exception as e:
            print(f"Failed to setup undetected Chrome, falling back to regular Chrome: {e}")
            return self.setup_fallback_driver()
    
    def setup_fallback_driver(self):
        """Fallback to regular Chrome with anti-detection measures"""
        options = webdriver.ChromeOptions()
        
        # Anti-detection arguments
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument(f"--user-agent={random.choice(self.user_agents)}")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins-discovery")
        
        service = Service(executable_path="/Users/ayush/CVisionary-AI Based Resume Screener With Job Matching/chromedriver")
        self.driver = webdriver.Chrome(service=service, options=options)
        self.wait = WebDriverWait(self.driver, 20)
        
        # Execute stealth scripts
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        return True
    
    def human_like_scroll(self):
        """Simulate human-like scrolling behavior"""
        scroll_pause_time = random.uniform(1, 3)
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        
        while True:
            # Scroll down to bottom
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(scroll_pause_time)
            
            # Calculate new scroll height and compare with last scroll height
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
            
            # Random scroll back up sometimes
            if random.random() < 0.3:
                scroll_up = random.randint(100, 500)
                self.driver.execute_script(f"window.scrollBy(0, -{scroll_up});")
                time.sleep(random.uniform(0.5, 1.5))
    
    def build_linkedin_job_url(self, job_title, location, experience_level=None):
        """Build LinkedIn job search URL"""
        base_url = "https://www.linkedin.com/jobs/search/?"
        
        params = []
        if job_title:
            params.append(f"keywords={quote(job_title)}")
        if location:
            params.append(f"location={quote(location)}")
        if experience_level:
            exp_levels = {
                "internship": "1",
                "entry": "2", 
                "associate": "3",
                "mid": "4",
                "director": "5",
                "executive": "6"
            }
            if experience_level.lower() in exp_levels:
                params.append(f"f_E={exp_levels[experience_level.lower()]}")
        
        params.append("f_TPR=r604800")  # Past week
        params.append("f_JT=F")  # Full-time
        
        return base_url + "&".join(params)
    
    def handle_linkedin_challenges(self):
        """Handle various LinkedIn anti-bot challenges"""
        try:
            # Check for CAPTCHA
            if "challenge" in self.driver.current_url.lower() or "captcha" in self.driver.page_source.lower():
                print("⚠️  CAPTCHA detected! Please solve it manually...")
                input("Press Enter after solving the CAPTCHA to continue...")
                return True
            
            # Check for login requirement
            if "authwall" in self.driver.current_url or "login" in self.driver.current_url:
                print("⚠️  LinkedIn login required. Please log in manually...")
                input("Press Enter after logging in to continue...")
                return True
            
            # Check for rate limiting
            if "rate" in self.driver.page_source.lower() and "limit" in self.driver.page_source.lower():
                print("⚠️  Rate limiting detected. Waiting 60 seconds...")
                time.sleep(60)
                return True
                
            return False
            
        except Exception as e:
            print(f"Error handling LinkedIn challenges: {e}")
            return False
    
    def scrape_linkedin_jobs(self, job_title, locations, experience_level=None, max_pages=3):
        """Scrape LinkedIn jobs for multiple locations"""
        all_results = {}
        
        if not self.setup_driver():
            return None
        
        try:
            for location in locations:
                print(f"\n🌍 Scraping jobs for location: {location}")
                location_results = []
                
                # Build URL for this location
                url = self.build_linkedin_job_url(job_title, location, experience_level)
                print(f"📍 Navigating to: {url}")
                
                # Navigate with human-like behavior
                self.driver.get("https://www.linkedin.com")
                time.sleep(random.uniform(2, 4))
                
                self.driver.get(url)
                time.sleep(random.uniform(3, 6))
                
                # Handle any challenges
                if self.handle_linkedin_challenges():
                    time.sleep(random.uniform(2, 4))
                
                # Scrape multiple pages
                for page in range(max_pages):
                    print(f"📄 Scraping page {page + 1} for {location}...")
                    
                    # Wait for job listings to load
                    try:
                        self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "jobs-search-results-list")))
                    except TimeoutException:
                        print("⚠️  Job listings not found, trying alternative selectors...")
                    
                    # Scroll to load more jobs
                    self.human_like_scroll()
                    time.sleep(random.uniform(2, 4))
                    
                    # Get page content
                    html = self.driver.page_source
                    location_results.append(html)
                    
                    # Try to go to next page
                    try:
                        next_button = self.driver.find_element(By.XPATH, "//button[@aria-label='Next']")
                        if next_button.is_enabled():
                            self.driver.execute_script("arguments[0].click();", next_button)
                            time.sleep(random.uniform(3, 6))
                        else:
                            print(f"✅ No more pages available for {location}")
                            break
                    except NoSuchElementException:
                        print(f"✅ Reached last page for {location}")
                        break
                
                all_results[location] = location_results
                
                # Random delay between locations
                if location != locations[-1]:  # Don't wait after the last location
                    wait_time = random.uniform(10, 20)
                    print(f"⏳ Waiting {wait_time:.1f} seconds before next location...")
                    time.sleep(wait_time)
        
        finally:
            if self.driver:
                self.driver.quit()
        
        return all_results
    
    def extract_and_clean_content(self, html_content):
        """Extract and clean job content from HTML"""
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Remove unwanted elements
        for element in soup(["script", "style", "nav", "footer", "header"]):
            element.decompose()
        
        # Focus on job-related content
        job_containers = soup.find_all(["div"], class_=lambda x: x and any(
            keyword in x.lower() for keyword in ["job", "result", "card", "listing"]
        ))
        
        if job_containers:
            content = ""
            for container in job_containers:
                content += container.get_text(separator="\n") + "\n\n"
        else:
            content = soup.get_text(separator="\n")
        
        # Clean content
        cleaned_content = "\n".join(
            line.strip() for line in content.splitlines() 
            if line.strip() and len(line.strip()) > 3
        )
        
        return cleaned_content

def split_dom_content(dom_content, max_length=6000):
    """Split content into chunks for processing"""
    return [
        dom_content[i : i + max_length] for i in range(0, len(dom_content), max_length)
    ]

def parse_with_ollama(dom_chunks, parse_description):
    """Parse content using Ollama"""
    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | model
    parsed_results = []
    
    for i, chunk in enumerate(dom_chunks, start=1):
        time.sleep(random.uniform(0.5, 2))
        print(f"🤖 Parsing batch: {i} of {len(dom_chunks)}")
        try:
            response = chain.invoke(
                {"dom_content": chunk, "parse_description": parse_description}
            )
            if response.strip():
                parsed_results.append(response)
        except Exception as e:
            print(f"Error parsing chunk {i}: {e}")
    
    return "\n".join(parsed_results)

def save_results(results, filename="linkedin_jobs_results.json"):
    """Save results to JSON file"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"💾 Results saved to {filename}")

def main():
    parser = argparse.ArgumentParser(
        description="Enhanced LinkedIn Job Scraper with Anti-Bot Detection",
        epilog="""
Examples:
  python linkedin_scraper.py "Software Engineer" "New York,San Francisco,Austin" "Extract job titles, companies, and salary ranges"
  python linkedin_scraper.py "Data Scientist" "London,Berlin,Amsterdam" "Extract all job details including requirements" --experience mid
  python linkedin_scraper.py "Product Manager" "Toronto,Vancouver" "Find remote work opportunities" --pages 5
        """
    )
    
    parser.add_argument(
        "job_title",
        help="Job title to search for (e.g., 'Software Engineer', 'Data Scientist')"
    )
    
    parser.add_argument(
        "locations",
        help="Comma-separated list of locations (e.g., 'New York,London,Tokyo')"
    )
    
    parser.add_argument(
        "parse_description",
        help="Describe what information to extract (e.g., 'Extract job titles and companies')"
    )
    
    parser.add_argument(
        "--experience",
        choices=["internship", "entry", "associate", "mid", "director", "executive"],
        help="Filter by experience level"
    )
    
    parser.add_argument(
        "--pages",
        type=int,
        default=3,
        help="Number of pages to scrape per location (default: 3)"
    )
    
    parser.add_argument(
        "--output",
        default="linkedin_jobs_results.json",
        help="Output filename for results (default: linkedin_jobs_results.json)"
    )
    
    args = parser.parse_args()
    
    # Parse locations
    locations = [loc.strip() for loc in args.locations.split(",")]
    
    print("🚀 Starting LinkedIn Job Scraper...")
    print(f"🎯 Job Title: {args.job_title}")
    print(f"📍 Locations: {', '.join(locations)}")
    print(f"📊 Experience Level: {args.experience or 'All levels'}")
    print(f"📄 Pages per location: {args.pages}")
    
    # Initialize scraper
    scraper = LinkedInScraper()
    
    try:
        # Scrape jobs
        raw_results = scraper.scrape_linkedin_jobs(
            args.job_title, 
            locations, 
            args.experience, 
            args.pages
        )
        
        if not raw_results:
            print("❌ No results obtained from scraping.")
            return
        
        # Process and parse results
        final_results = {}
        
        for location, html_pages in raw_results.items():
            print(f"\n🔍 Processing results for {location}...")
            
            location_content = ""
            for html in html_pages:
                cleaned = scraper.extract_and_clean_content(html)
                location_content += cleaned + "\n\n"
            
            if location_content.strip():
                # Split and parse content
                dom_chunks = split_dom_content(location_content)
                parsed_result = parse_with_ollama(dom_chunks, args.parse_description)
                
                if parsed_result.strip():
                    final_results[location] = parsed_result
                else:
                    final_results[location] = "No matching content found."
            else:
                final_results[location] = "No content extracted."
        
        # Display results
        print("\n" + "="*60)
        print("📋 SCRAPING RESULTS")
        print("="*60)
        
        for location, result in final_results.items():
            print(f"\n🌍 Location: {location}")
            print("-" * 40)
            print(result)
            print()
        
        # Save results
        save_results({
            "search_params": {
                "job_title": args.job_title,
                "locations": locations,
                "experience_level": args.experience,
                "pages_per_location": args.pages,
                "parse_description": args.parse_description
            },
            "results": final_results,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }, args.output)
        
        print(f"✅ Scraping completed successfully!")
        
    except KeyboardInterrupt:
        print("\n⏹️  Scraping interrupted by user.")
    except Exception as e:
        print(f"❌ Error occurred: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()