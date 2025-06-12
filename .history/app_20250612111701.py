import os
import json
import logging
import re
from typing import Dict, List, Optional
from flask import Flask, render_template, request, flash, redirect, url_for, send_file, session 
from werkzeug.utils import secure_filename
from langchain_core.prompts import PromptTemplate
from langchain_ollama import OllamaLLM
from resume_scraper.resume_praser import parse_resume_from_file, generate_resume_summary, infer_career_interests # ADDED infer_career_interests
from resume_scraper.scraper import scrape_job_links_from_search_page, scrape_detailed_job_description
import io
import time
import urllib.parse
from dotenv import load_dotenv

# For PDF generation
from weasyprint import HTML 

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="frontend")
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY') 
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max file size

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'rtf'}

class ResumeJobMatcher:
    def __init__(self, model_name="llama3.2"):
        try:
            self.llm = OllamaLLM(model=model_name)
            logger.info(f"Initialized LLM model: {model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize LLM model: {e}")
            raise

    # Modified scrape_job_listings to use inferred interests
    def scrape_job_listings(self, cities: List[str], inferred_keywords: List[str]) -> List[Dict]:
        """
        Orchestrates scraping LinkedIn job listings from search pages and then detailed job pages.
        Uses dynamically inferred keywords from the resume.
        """
        all_job_listings = []
        seen_job_urls = set() # To prevent processing the same job URL multiple times

        base_linkedin_search_url = "https://www.linkedin.com/jobs/search/?f_TPR=r86400&" # r86400 = past 24 hours
        
        # Use the inferred keywords directly for search queries
        search_keywords = inferred_keywords
        if not search_keywords:
            logger.warning("No specific career interests inferred. Using general keywords.")
            search_keywords = ["general assistant", "administrator", "entry level", "associate"] # Fallback for very generic resumes

        for city in cities:
            encoded_city = urllib.parse.quote_plus(f"{city}, Nepal")
            for keyword in search_keywords:
                encoded_keyword = urllib.parse.quote_plus(keyword)
                search_url = f"{base_linkedin_search_url}keywords={encoded_keyword}&location={encoded_city}"
                logger.info(f"Scraping job links from search URL: {search_url}")
                
                initial_job_cards = scrape_job_links_from_search_page(search_url)
                logger.info(f"Found {len(initial_job_cards)} initial job cards for '{keyword}' in '{city}'")

                for card in initial_job_cards:
                    job_url = card.get('url')
                    if not job_url or job_url in seen_job_urls:
                        logger.debug(f"Skipping duplicate or invalid job URL: {job_url}")
                        continue
                    
                    seen_job_urls.add(job_url)
                    logger.info(f"Scraping detailed description for: {job_url}")
                    detailed_description = scrape_detailed_job_description(job_url)
                    time.sleep(1) # Small delay between detailed scrapes

                    if detailed_description:
                        # Extract structured details using LLM from the detailed description
                        job_listing_details = self._extract_job_details(detailed_description)
                        if job_listing_details:
                            # Add the original URL to the extracted details
                            job_listing_details['job_url'] = job_url
                            # Use details from initial card as fallback/supplement
                            job_listing_details['job_title'] = job_listing_details.get('job_title') or card.get('title')
                            job_listing_details['company'] = job_listing_details.get('company') or card.get('company')
                            job_listing_details['location'] = job_listing_details.get('location') or card.get('location')
                            all_job_listings.append(job_listing_details)
                            logger.debug(f"Added detailed job: {job_listing_details.get('job_title')} at {job_listing_details.get('company')}")
                        else:
                            logger.warning(f"Could not extract structured details from {job_url}")
                    else:
                        logger.warning(f"Failed to scrape detailed description for {job_url}")
        
        logger.info(f"Total unique detailed job listings extracted: {len(all_job_listings)}")
        return all_job_listings


    def _extract_job_details(self, detailed_job_content: str) -> Optional[Dict]:
        """
        Extracts structured job details from a *full job description content*.
        """
        job_extract_prompt = PromptTemplate(
            input_variables=["job_content"],
            template="""Extract structured job details from the following full job posting content and return ONLY a valid JSON object. Do not include any explanatory text, code block markers (e.g., ```json), or other content outside the JSON object. Ensure all strings are properly escaped and valid for JSON.

Full Job Posting Content:
{job_content}

Return a JSON object with the following structure:
{{
    "job_title": "",
    "company": "",
    "location": "",
    "requirements": [],
    "skills_required": [],
    "experience_level": "",
    "job_description": ""
}}

Instructions:
- Identify the job title, company, and location from the content.
- For "requirements", extract ALL explicitly mentioned qualifications, experience, or prerequisites (e.g., "3 years of experience", "Bachelor's degree in Computer Science", "Must have a valid driving license"). If implied, infer reasonable ones based on the role.
- For "skills_required", extract ALL explicitly mentioned skills or tools (e.g., "Python", "SQL", "AWS", "Jira", "Communication"). If implied, infer likely skills based on the job title.
- For "experience_level", determine if the job is "Entry Level", "Mid Level", "Senior Level", "Director Level", "Executive Level", or leave empty if not specified/inferrable.
- For "job_description", summarize the job's responsibilities or description comprehensively.
- If information is not explicitly found, make reasonable inferences or use empty strings/lists as appropriate.
- If the Company name or location is empty, try to infer or leave empty.
- Prioritize explicit mentions over inferences.
- Ensure the "requirements" and "skills_required" lists are comprehensive.
"""
        )
        try:
            response = self.llm.invoke(job_extract_prompt.format(job_content=detailed_job_content))
            job_details = self._clean_json_response(response, expect_array=False)
            return job_details
        except Exception as e:
            logger.error(f"Error extracting job details with LLM: {e}")
            logger.error(f"Problematic content (first 500 chars): {detailed_job_content[:500]}")
            return None

    def _clean_json_response(self, response: str, expect_array: bool = False) -> Dict | List:
        # Remove code block markers and strip whitespace
        response = response.replace("```json", "").replace("```", "").strip()

        # Normalize Unicode characters and remove invalid control characters
        try:
            response = response.encode('utf-8').decode('utf-8', errors='ignore') # Use 'ignore' for robustness
            response = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', response)
        except Exception as e:
            logger.error(f"Unicode cleaning error: {e}")
            logger.error(f"Raw response during unicode cleaning: {response}")
            return [] if expect_array else {}

        # Define regex for JSON object or array
        json_pattern = r'\{[\s\S]*?\}$' if not expect_array else r'\[[\s\S]*?\]$'
        matches = re.findall(json_pattern, response)

        if not matches:
            logger.error("No JSON object or array found in response")
            logger.error(f"Raw LLM Response: {response}")
            return [] if expect_array else {}

        json_str = matches  # Take the first match

        # Attempt to fix incomplete JSON (simple balancing for braces/brackets)
        try:
            if not expect_array:
                open_count = json_str.count('{')
                close_count = json_str.count('}')
                if open_count > close_count:
                    json_str += '}' * (open_count - close_count)
                elif close_count > open_count:
                    # This is more complex, might need to truncate from end if malformed
                    json_str = json_str[:json_str.rfind('}') + 1] # try to find the last valid closing brace
            else:
                open_count = json_str.count('[')
                close_count = json_str.count(']')
                if open_count > close_count:
                    json_str += ']' * (open_count - close_count)
                elif close_count > open_count:
                    json_str = json_str[:json_str.rfind(']') + 1]

            # Parse JSON
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Could not parse JSON after simple fix: {e}")
            logger.error(f"Problematic JSON string: {json_str}")
            logger.error(f"Raw LLM Response (full): {response}")
            
            # More aggressive fallback: try to find the first '{' or '[' and last '}' or ']'
            try:
                start_idx = json_str.find('{' if not expect_array else '[')
                end_idx = json_str.rfind('}' if not expect_array else ']')
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    return json.loads(json_str[start_idx : end_idx + 1])
            except json.JSONDecodeError as e_fallback:
                logger.error(f"Fallback JSON parsing also failed: {e_fallback}")
                logger.error(f"Fallback string attempt: {json_str[start_idx : end_idx + 1]}")
            return [] if expect_array else {}

    def extract_resume_keywords(self, resume_data: Dict) -> List[str]:
        keyword_prompt = PromptTemplate(
            input_variables=["resume_data"],
            template=""".

                Extract the most important 10-15 actionable keywords from this resume that would be relevant for job matching and return ONLY a valid JSON array. Do not include any explanatory text or code block markers. Ensure all strings are properly escaped and valid for JSON.

                Resume Data:
                {resume_data}

                Focus on extracting:
                - Specific technical skills and technologies (e.g., Python, AWS, Docker, React, SQL)
                - Programming languages, frameworks, libraries
                - Tools and platforms (e.g., Jira, Git, Salesforce)
                - Methodologies (e.g., Agile, Scrum)
                - Certifications (e.g., PMP, AWS Certified Solutions Architect)
                - Key qualifications and specific job roles previously held (e.g., "Data Scientist", "DevOps Engineer")
                - Soft skills relevant to professional roles (e.g., Communication, Problem-solving, Leadership)
                - Industry-specific terminology.

                Return: []"""

        )
        try:
            response = self.llm.invoke(keyword_prompt.format(resume_data=json.dumps(resume_data)))
            response_data = self._clean_json_response(response, expect_array=True)
            if isinstance(response_data, list):
                return response_data
            logger.warning("Unexpected response format for keywords from LLM. Attempting to use parsed skills.")
            # Fallback to skills extracted by resume parser if LLM fails
            return resume_data.get("Technical Skills", []) + resume_data.get("Soft Skills", [])
        except Exception as e:
            logger.error(f"Error extracting resume keywords with LLM: {e}")
            return resume_data.get("Technical Skills", []) + resume_data.get("Soft Skills", []) # Fallback

    def match_resume_to_jobs(self, resume_data: Dict, job_listings: List[Dict]) -> List[Dict]:
        keywords = self.extract_resume_keywords(resume_data)
        logger.info(f"Extracted keywords from resume: {keywords}")

        # Try to infer a primary job title from the resume for better matching context
        primary_job_title = resume_data.get("Work Experience", [{}]).get("Position") \
                           or resume_data.get("Projects", [{}]).get("Name") \
                           or resume_data.get("Full Name", "").split()[-1] + " (inferred)" # last word of name as potential role

        matching_prompt = PromptTemplate(
            input_variables=["resume_details", "job_listing", "keywords", "primary_job_title"],
            template="""Compare the provided resume details with a job listing and return ONLY a valid JSON object. Do not include any explanatory text or code block markers. Ensure all strings are properly escaped and valid for JSON. The match_score must be an integer between 0 and 100.

Resume Details:
{resume_details}

Job Listing:
{job_listing}

Key Resume Keywords: {keywords}
Inferred Primary Job Title from Resume: {primary_job_title}

Return:
{{
    "match_score": 0,
    "matched_skills": [],
    "missing_skills": [],
    "match_reasoning": "",
    "job_fit": ""
}}

Evaluation Criteria:
- Calculate match_score (0-100) based on:
  - Skill overlap: How many job's required skills match resume keywords and parsed skills (40% weight).
  - Experience alignment: If resume's work experience and total years of experience (if inferrable) align with job's experience_level and requirements (30% weight).
  - Requirement fit: How well the resume's qualifications, education, and other sections meet the job's stated requirements (30% weight).
- List 'matched_skills' as specific skills from job.skills_required that are clearly present in the resume keywords or parsed resume details.
- List 'missing_skills' as specific skills from job.skills_required that are NOT found in the resume.
- Provide detailed 'match_reasoning' explaining the calculated score, highlighting key strengths and weaknesses based on the resume. Be constructive in suggesting improvements for missing skills.
- Set 'job_fit' to "Excellent Match" (80-100), "Good Match" (60-79), "Moderate Match" (40-59), or "Poor Match" (0-39).
- If data is insufficient, infer reasonable values and explain in match_reasoning.
- Make sure 'matched_skills' and 'missing_skills' are distinct lists of actual skills mentioned.
"""
        )
        matched_jobs = []
        total_jobs = len(job_listings)
        for i, job in enumerate(job_listings, 1):
            try:
                logger.info(f"Matching job {i}/{total_jobs}: {job.get('job_title', 'Unknown Job')} at {job.get('company', 'Unknown Company')}")
                match_result = self.llm.invoke(
                    matching_prompt.format(
                        resume_details=json.dumps(resume_data),
                        job_listing=json.dumps(job),
                        keywords=", ".join(keywords),
                        primary_job_title=primary_job_title
                    )
                )
                match_data = self._clean_json_response(match_result, expect_array=False)
                
                if not match_data or "match_score" not in match_data:
                    logger.warning(f"Invalid match data for job {i}: {job.get('job_title')}, skipping.")
                    continue

                # Ensure match_score is an integer and within range
                try:
                    match_score = int(match_data.get("match_score", 0))
                except ValueError:
                    match_score = 0 # Default to 0 if conversion fails
                
                match_data["match_score"] = max(0, min(100, match_score)) # Clamp between 0 and 100

                # Fallback and consistency check for match_score and job_fit
                if not isinstance(match_data["match_score"], int): # Re-check after conversion attempt
                    match_data["match_score"] = 0 

                # Update job_fit based on adjusted match_score
                if match_data["match_score"] >= 80:
                    match_data["job_fit"] = "Excellent Match"
                elif match_data["match_score"] >= 60:
                    match_data["job_fit"] = "Good Match"
                elif match_data["match_score"] >= 40:
                    match_data["job_fit"] = "Moderate Match"
                else:
                    match_data["job_fit"] = "Poor Match"

                # Ensure match_reasoning is populated
                if not match_data.get("match_reasoning"):
                    matched_skills_count = len(match_data.get("matched_skills", []))
                    missing_skills_count = len(match_data.get("missing_skills", []))
                    job_skills_count = len(job.get("skills_required", []))
                    match_data["match_reasoning"] = (
                        f"Based on a {match_data['match_score']}% match: Matched {matched_skills_count} out of {job_skills_count} required skills. "
                        f"Identified {missing_skills_count} skills for potential development. "
                        f"Resume aligns with job experience and requirements."
                    )

                matched_job = {**job, "match_details": match_data}
                matched_jobs.append(matched_job)
            except Exception as e:
                logger.error(f"Error matching resume to job {job.get('job_title', 'Unknown Job')}: {e}")
                # Log the job data that caused the error for debugging
                logger.error(f"Job data causing error: {json.dumps(job, indent=2)}")

        matched_jobs.sort(key=lambda x: x.get('match_details', {}).get('match_score', 0), reverse=True)
        logger.info(f"Completed matching. Found {len(matched_jobs)} suitable jobs.")
        return matched_jobs

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/features')
def features():
    return render_template('features.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        if 'resume' not in request.files:
            flash('Please upload a resume.', 'error')
            return redirect(request.url)

        file = request.files['resume']

        if file.filename == '':
            flash('No file selected.', 'error')
            return redirect(request.url)

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            # Save the file to disk temporarily for parsing
            try:
                file.save(filepath)
                logger.info(f"File saved to {filepath}")
            except Exception as e:
                flash(f"Error saving file: {str(e)}", 'error')
                logger.error(f"Error saving file {filepath}: {e}")
                return redirect(request.url)

            resume_data = None
            resume_summary = None
            matched_jobs = None

            try:
                # Parse resume from the saved file
                with open(filepath, 'rb') as resume_file_for_parsing:
                    resume_data = parse_resume_from_file(resume_file_for_parsing)

                if 'error' in resume_data:
                    flash(f"Error parsing resume: {resume_data['error']}", 'error')
                    logger.error(f"Resume parsing error: {resume_data['error']}")
                    return render_template('upload.html') # Render with only error

                # Store resume_data in session for PDF download
                session['parsed_resume_data'] = resume_data 

                # Generate resume summary
                resume_summary = generate_resume_summary(resume_data)
                if not resume_summary:
                    flash("Could not generate resume summary.", 'warning')
                    logger.warning("Failed to generate resume summary.")

                matcher = ResumeJobMatcher(model_name="llama3.2")
                
                # Dynamically infer career interests from the full resume data
                inferred_job_keywords = infer_career_interests(resume_data)
                if not inferred_job_keywords:
                    flash("Could not infer specific job interests from your resume. Searching with general terms.", 'info')
                    inferred_job_keywords = ["general"] # Fallback if LLM fails to infer anything

                nepal_cities = ["Kathmandu", "Pokhara", "Lalitpur"] # Major cities in Nepal
                # Pass the inferred keywords to the scraping function
                job_listings = matcher.scrape_job_listings(nepal_cities, inferred_job_keywords)

                if not job_listings:
                    flash('No job listings found for the inferred keywords in specified cities. Please try again later or adjust your resume content.', 'warning')
                    # Still show resume data if successfully parsed
                    return render_template('upload.html', resume_data=resume_data, resume_summary=resume_summary)

                matched_jobs = matcher.match_resume_to_jobs(resume_data, job_listings)

                if not matched_jobs:
                    flash('No suitable job matches found based on your resume. Try refining your resume or check back later for new listings.', 'info')
                    # Still show resume data
                    return render_template('upload.html', resume_data=resume_data, resume_summary=resume_summary)

                # Limit to top 5 matches for display
                top_matches = matched_jobs[:5]
                return render_template('upload.html', matched_jobs=top_matches, resume_data=resume_data, resume_summary=resume_summary)

            except Exception as e:
                logger.exception("An unhandled error occurred during upload processing.")
                flash(f"An unexpected error occurred: {str(e)}. Please try again.", 'error')
                return render_template('upload.html', resume_data=resume_data, resume_summary=resume_summary) # Show what we have
            finally:
                if os.path.exists(filepath):
                    os.remove(filepath)  # Clean up uploaded file
                    logger.info(f"Cleaned up uploaded file: {filepath}")

    return render_template('upload.html', matched_jobs=None, resume_data=None, resume_summary=None)

@app.route('/login-signup')
def login_signup():
    return render_template('login-signup.html')

@app.route('/download_results')
def download_results():
    matched_jobs_json_str = request.args.get('matched_jobs', '[]')
    try:
        matched_jobs = json.loads(matched_jobs_json_str)
    except json.JSONDecodeError:
        flash('Error decoding job results for download.', 'error')
        return redirect(url_for('upload'))
    
    json_data = json.dumps(matched_jobs, indent=2)
    return send_file(
        io.BytesIO(json_data.encode('utf-8')), # Ensure utf-8 encoding
        mimetype='application/json',
        as_attachment=True,
        download_name='matched_jobs.json'
    )

@app.route('/download_parsed_resume_pdf')
def download_parsed_resume_pdf():
    parsed_resume_data = session.get('parsed_resume_data')
    if not parsed_resume_data:
        flash('No parsed resume data available for download. Please upload a resume first.', 'error')
        return redirect(url_for('upload'))

    # Render the HTML template specifically for PDF conversion
    rendered_html = render_template('resume_pdf_template.html', resume_data=parsed_resume_data)

    # Convert HTML to PDF using WeasyPrint
    pdf_bytes = io.BytesIO()
    try:
        HTML(string=rendered_html).write_pdf(pdf_bytes)
        pdf_bytes.seek(0) # Rewind the BytesIO object to the beginning

        full_name = parsed_resume_data.get('Full Name', 'Parsed_Resume').replace(' ', '_')
        download_filename = f"{full_name}_CVisionary.pdf"

        return send_file(
            pdf_bytes,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=download_filename
        )
    except Exception as e:
        logger.exception("Error generating PDF for parsed resume.")
        flash(f"Error generating PDF: {str(e)}", 'error')
        return redirect(url_for('upload'))


if __name__ == '__main__':
    app.run(debug=True)
