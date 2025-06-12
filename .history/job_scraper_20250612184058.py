import os
import json
import logging
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from selenium.common.exceptions import WebDriverException, TimeoutException
import random

# Import necessary functions from your existing modules
from resume_scraper.scraper import scrape_job_links_from_search_page, scrape_detailed_job_description
# Import the Flask app and db object from cli4.py
# This allows job_scraper.py to use the same SQLAlchemy database instance and models
from cli import app, db, JobListing, ResumeJobMatcher # Ensure ResumeJobMatcher is imported for _extract_job_details
from dotenv import load_dotenv

# Load environment variables (for GEMINI_API_KEY if used by LLM within matcher)
load_dotenv()

# Configure logging for the scraper
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_job_scraping():
    with app.app_context():
        logger.info("Starting background job scraping process...")

        matcher = ResumeJobMatcher(model_name="llama3.2")

        nepal_cities = ["Kathmandu", "Pokhara", "Lalitpur"]
        # Use a more conservative time window and add more search parameters
        base_linkedin_search_url = "https://www.linkedin.com/jobs/search/?"
        search_params = {
            "f_TPR": "r86400",     # Last 24 hours instead of 7 days to reduce load
            "sortBy": "DD",        # Sort by date
            "position": "1",
            "pageNum": "0",
            "f_AL": "true",       # Easy apply only (tends to have better success rate)
            "distance": "25"       # 25 km radius
        }

        # Reduce the number of keywords to avoid too many requests
        primary_keywords = [
            "Software", "Developer", "Data Scientist", "Analyst",
            "Marketing", "Sales", "Customer Service", "Admin Assistant",
            "HR", "Teacher", "Engineer", "Project Manager", "IT Support"
        ]

        total_scraped_jobs = 0
        total_new_jobs = 0
        total_updated_jobs = 0
        max_retries = 3
        base_delay = 5  # Base delay between retries in seconds

        for city in nepal_cities:
            for keyword in primary_keywords:
                for attempt in range(max_retries):
                    try:
                        # Construct search URL with parameters
                        params = search_params.copy()
                        params["keywords"] = keyword
                        params["location"] = f"{city}, Nepal"
                        param_strings = [f"{k}={urllib.parse.quote_plus(str(v))}" for k, v in params.items()]
                        search_url = base_linkedin_search_url + "&".join(param_strings)
                        
                        logger.info(f"Attempt {attempt + 1}/{max_retries}: Scraping jobs for '{keyword}' in '{city}'")
                        
                        initial_job_cards = scrape_job_links_from_search_page(search_url)
                        if initial_job_cards:
                            logger.info(f"Found {len(initial_job_cards)} job cards for '{keyword}' in '{city}'")
                            
                            for card in initial_job_cards:
                                job_url = card.get('url')
                                if not job_url:
                                    continue

                                # Check if job exists and is fresh enough
                                existing_job = JobListing.query.filter_by(job_url=job_url).first()
                                if existing_job and existing_job.scraped_at > datetime.utcnow() - timedelta(hours=12):
                                    total_scraped_jobs += 1
                                    continue

                                # Add exponential backoff between job detail scraping
                                retry_count = 0
                                while retry_count < max_retries:
                                    try:
                                        detailed_description = scrape_detailed_job_description(job_url)
                                        if detailed_description:
                                            break
                                    except WebDriverException as e:
                                        retry_count += 1
                                        if retry_count < max_retries:
                                            sleep_time = base_delay * (2 ** retry_count) + random.uniform(1, 3)
                                            logger.warning(f"Retry {retry_count} for {job_url}. Waiting {sleep_time:.1f}s")
                                            time.sleep(sleep_time)
                                        else:
                                            logger.error(f"Failed to scrape {job_url} after {max_retries} attempts")
                                            continue

                                if detailed_description:
                                    try:
                                        job_listing_details = matcher._extract_job_details(detailed_description)
                                        if job_listing_details:
                                            # Update with card data and prepare for storage
                                            job_listing_details.update({
                                                'job_title': job_listing_details.get('job_title') or card.get('title'),
                                                'company': job_listing_details.get('company') or card.get('company'),
                                                'location': job_listing_details.get('location') or card.get('location'),
                                                'job_url': job_url,
                                                'job_description': job_listing_details.get('job_description') or detailed_description
                                            })

                                            # Convert lists to JSON strings
                                            job_listing_details['requirements'] = json.dumps(job_listing_details.get('requirements', []))
                                            job_listing_details['skills_required'] = json.dumps(job_listing_details.get('skills_required', []))

                                            if existing_job:
                                                # Update existing job
                                                for key, value in job_listing_details.items():
                                                    if hasattr(existing_job, key):
                                                        setattr(existing_job, key, value)
                                                existing_job.scraped_at = datetime.utcnow()
                                                total_updated_jobs += 1
                                            else:
                                                # Create new job
                                                new_job = JobListing(**job_listing_details)
                                                new_job.date_posted = datetime.utcnow()
                                                new_job.scraped_at = datetime.utcnow()
                                                db.session.add(new_job)
                                                total_new_jobs += 1

                                            try:
                                                db.session.commit()
                                                total_scraped_jobs += 1
                                            except Exception as db_error:
                                                logger.error(f"Database error: {db_error}")
                                                db.session.rollback()

                                            # Add random delay between jobs
                                            time.sleep(random.uniform(2, 5))
                                    except Exception as e:
                                        logger.error(f"Error processing job details: {e}")
                                        continue

                            # Successfully processed this keyword/city combination
                            break
                        else:
                            logger.warning(f"No jobs found for {keyword} in {city} on attempt {attempt + 1}")
                            if attempt < max_retries - 1:
                                sleep_time = base_delay * (2 ** attempt) + random.uniform(1, 3)
                                logger.info(f"Waiting {sleep_time:.1f}s before retry...")
                                time.sleep(sleep_time)

                    except Exception as e:
                        logger.error(f"Error during job scraping for {keyword} in {city}: {e}")
                        if attempt < max_retries - 1:
                            sleep_time = base_delay * (2 ** attempt) + random.uniform(1, 3)
                            logger.info(f"Waiting {sleep_time:.1f}s before retry...")
                            time.sleep(sleep_time)
                        continue

                # Add delay between different keywords
                time.sleep(random.uniform(5, 10))

            # Add longer delay between cities
            time.sleep(random.uniform(15, 30))

        logger.info(f"Background scraping completed!")
        logger.info(f"Total jobs processed: {total_scraped_jobs}")
        logger.info(f"New jobs added: {total_new_jobs}")
        logger.info(f"Existing jobs updated: {total_updated_jobs}")

if __name__ == '__main__':
    # You would typically schedule this script (e.g., with cron on Linux/macOS, Task Scheduler on Windows)
    # For manual testing, just run it directly: python job_scraper.py
    try:
        run_job_scraping()
    except Exception as e:
        logger.exception(f"An error occurred during job scraping: {e}")