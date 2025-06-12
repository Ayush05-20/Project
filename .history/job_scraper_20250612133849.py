
import os
import json
import logging
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from selenium.common.exceptions import WebDriverException, TimeoutException

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
    with app.app_context(): # Essential for Flask-SQLAlchemy outside of Flask routes
        logger.info("Starting background job scraping process...")

        matcher = ResumeJobMatcher(model_name="llama3.2") # Initialize LLM for job detail extraction

        nepal_cities = ["Kathmandu", "Pokhara", "Lalitpur"]
        # Broad keywords to cover various industries
        # Adjusted f_TPR to r604800 for jobs posted in the last 7 days
        base_linkedin_search_url = "https://www.linkedin.com/jobs/search/?f_TPR=r604800&" 
        
        # Comprehensive list of keywords covering various industries
        # Prioritize common roles first
        generic_keywords = [
            "Software Engineer", "Developer", "Data Scientist", "Analyst", "Manager",
            "Marketing", "Sales", "Customer Service", "Admin Assistant", "Accountant",
            "HR", "Human Resources", "Teacher", "Nurse", "Healthcare", "Engineer",
            "Project Manager", "IT Support", "Content Writer", "Graphic Designer",
            "Financial Analyst", "Operations Manager", "Business Development",
            "Logistics", "Supply Chain", "Research", "Consultant", "Web Developer",
            "Mobile Developer", "DevOps", "Cloud Engineer", "System Administrator",
            "Network Engineer", "Cybersecurity", "Product Manager", "UX Designer",
            "UI Designer", "Recruiter", "Legal", "Construction", "Architect",
            "Civil Engineer", "Electrical Engineer", "Mechanical Engineer", "Doctor",
            "Pharmacist", "Medical Assistant", "Retail", "Hospitality", "Chef",
            "Driver", "Delivery", "Security Guard", "Electrician", "Plumber",
            "Technician", "Trainer", "Copywriter", "Editor", "Journalist",
            "Data Entry", "Virtual Assistant", "Executive Assistant", "Office Manager"
        ]
        
        # Add some very broad terms to catch anything missed by specifics
        very_broad_keywords = ["Jobs", "Vacancies", "Hiring"]
        search_keywords = list(set(generic_keywords)) # Remove potential duplicates

        total_scraped_jobs = 0
        total_new_jobs = 0
        total_updated_jobs = 0

        for city in nepal_cities:
            encoded_city = urllib.parse.quote_plus(f"{city}, Nepal")
            
            # Combine broad and specific keywords to ensure wider coverage
            current_search_keywords = list(set(search_keywords + very_broad_keywords))

            for keyword in current_search_keywords:
                encoded_keyword = urllib.parse.quote_plus(keyword)
                search_url = f"{base_linkedin_search_url}keywords={encoded_keyword}&location={encoded_city}"
                logger.info(f"Scraping job links for '{keyword}' in '{city}' from search URL: {search_url}")
                
                initial_job_cards = scrape_job_links_from_search_page(search_url)
                logger.info(f"Found {len(initial_job_cards)} initial job cards for '{keyword}' in '{city}'")

                for card in initial_job_cards:
                    job_url = card.get('url')
                    if not job_url:
                        logger.debug(f"Skipping job card with no URL: {card}")
                        continue

                    # Check if job already exists in DB
                    existing_job = JobListing.query.filter_by(job_url=job_url).first()

                    detailed_description = None
                    if existing_job:
                        # Decide if we need to re-scrape an existing job (e.g., if it's old or description is missing)
                        # For simplicity, let's re-scrape if it was scraped more than 3 days ago OR if desc is empty
                        if existing_job.scraped_at < datetime.utcnow() - timedelta(days=3) or not existing_job.job_description:
                            logger.info(f"Re-scraping detailed description for existing job: {job_url}")
                            try:
                                detailed_description = scrape_detailed_job_description(job_url)
                                time.sleep(1) # Small delay
                            except WebDriverException as e:
                                logger.error(f"WebDriver error re-scraping {job_url}: {e}")
                                continue
                        else:
                            logger.debug(f"Job already in DB and recently scraped: {job_url}")
                            total_scraped_jobs += 1
                            continue # No need to re-process if already fresh
                    else:
                        logger.info(f"Scraping detailed description for new job: {job_url}")
                        try:
                            detailed_description = scrape_detailed_job_description(job_url)
                            time.sleep(1) # Small delay
                        except WebDriverException as e:
                            logger.error(f"WebDriver error scraping new job {job_url}: {e}")
                            continue


                    if detailed_description:
                        # Extract structured details using LLM from the detailed description
                        job_listing_details = matcher._extract_job_details(detailed_description) # Call internal LLM method
                        if job_listing_details:
                            # Supplement LLM extracted details with initial card data if LLM missed something
                            job_listing_details['job_title'] = job_listing_details.get('job_title') or card.get('title')
                            job_listing_details['company'] = job_listing_details.get('company') or card.get('company')
                            job_listing_details['location'] = job_listing_details.get('location') or card.get('location')
                            job_listing_details['job_url'] = job_url # Ensure URL is always present
                            job_listing_details['job_description'] = job_listing_details.get('job_description') or detailed_description # Keep full description if summary is brief
                            
                            # Convert lists to JSON strings for storage
                            job_listing_details['requirements'] = json.dumps(job_listing_details.get('requirements', []))
                            job_listing_details['skills_required'] = json.dumps(job_listing_details.get('skills_required', []))

                            if existing_job:
                                # Update existing job
                                existing_job.job_title = job_listing_details['job_title']
                                existing_job.company = job_listing_details['company']
                                existing_job.location = job_listing_details['location']
                                existing_job.requirements = job_listing_details['requirements']
                                existing_job.skills_required = job_listing_details['skills_required']
                                existing_job.experience_level = job_listing_details['experience_level']
                                existing_job.job_description = job_listing_details['job_description']
                                existing_job.scraped_at = datetime.utcnow()
                                db.session.commit()
                                total_updated_jobs += 1
                                logger.debug(f"Updated job: {job_listing_details.get('job_title')}")
                            else:
                                # Add new job
                                new_job = JobListing(
                                    job_title=job_listing_details['job_title'],
                                    company=job_listing_details['company'],
                                    location=job_listing_details['location'],
                                    job_url=job_listing_details['job_url'],
                                    requirements=job_listing_details['requirements'],
                                    skills_required=job_listing_details['skills_required'],
                                    experience_level=job_listing_details['experience_level'],
                                    job_description=job_listing_details['job_description'],
                                    date_posted=datetime.utcnow() # Assume posted now for simplicity, or try to infer from page if possible
                                )
                                db.session.add(new_job)
                                db.session.commit()
                                total_new_jobs += 1
                                logger.debug(f"Added new job: {job_listing_details.get('job_title')}")
                            total_scraped_jobs += 1
                        else:
                            logger.warning(f"Could not extract structured details from {job_url}")
                    else:
                        logger.warning(f"Failed to scrape detailed description for {job_url}")
        
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