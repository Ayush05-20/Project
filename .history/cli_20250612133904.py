--- START OF FILE cli4.py ---
import os
import json
import logging
import re
from datetime import datetime, timedelta # ADDED timedelta
from typing import Dict, List, Optional
from flask import Flask, render_template, request, flash, redirect, url_for, send_file, session
from werkzeug.utils import secure_filename
from langchain_core.prompts import PromptTemplate
from langchain_ollama import OllamaLLM
from resume_scraper.resume_praser import parse_resume_from_file, generate_resume_summary, infer_career_interests
# Removed direct import of scraper functions as they will be used by job_scraper.py
import io
import time
import urllib.parse
from dotenv import load_dotenv

# For PDF generation
from weasyprint import HTML 

# For Database
from flask_sqlalchemy import SQLAlchemy # ADDED

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

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///jobs.db' # SQLite database file
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Suppress warning

db = SQLAlchemy(app) # Initialize SQLAlchemy

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'rtf'}

# Job Listing Database Model
class JobListing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_title = db.Column(db.String(255), nullable=False)
    company = db.Column(db.String(255), nullable=True)
    location = db.Column(db.String(255), nullable=True)
    job_url = db.Column(db.String(500), unique=True, nullable=False)
    requirements = db.Column(db.Text, nullable=True) # Stored as JSON string
    skills_required = db.Column(db.Text, nullable=True) # Stored as JSON string
    experience_level = db.Column(db.String(100), nullable=True)
    job_description = db.Column(db.Text, nullable=True)
    date_posted = db.Column(db.DateTime, default=datetime.utcnow) # When the job was posted (inferred)
    scraped_at = db.Column(db.DateTime, default=datetime.utcnow) # When we scraped it

    def __repr__(self):
        return f'<JobListing {self.job_title} at {self.company}>'

    def to_dict(self):
        return {
            'id': self.id,
            'job_title': self.job_title,
            'company': self.company,
            'location': self.location,
            'job_url': self.job_url,
            'requirements': json.loads(self.requirements) if self.requirements else [],
            'skills_required': json.loads(self.skills_required) if self.skills_required else [],
            'experience_level': self.experience_level,
            'job_description': self.job_description,
            'date_posted': self.date_posted.isoformat() if self.date_posted else None,
            'scraped_at': self.scraped_at.isoformat() if self.scraped_at else None
        }

# Create database tables if they don't exist
with app.app_context():
    db.create_all()

class ResumeJobMatcher:
    def __init__(self, model_name="llama3.2"):
        try:
            self.llm = OllamaLLM(model=model_name)
            logger.info(f"Initialized LLM model: {model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize LLM model: {e}")
            raise

    # This method is now used by the background scraper, not directly by Flask upload route
    # The scraping logic itself is moved to job_scraper.py
    def _extract_job_details(self, detailed_job_content: str) -> Optional[Dict]:
        """
        Extracts structured job details from a *full job description content*.
        This function is kept here as it's an LLM operation, but called from job_scraper.py.
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

        # FIX: The original code had `json_str = matches`. This should be `json_str = matches`
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
    return '.' in filename and filename.rsplit('.', 1).lower() in ALLOWED_EXTENSIONS

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
                with open(filepath, 'rb') as resume_file_for_parsing:
                    resume_data = parse_resume_from_file(resume_file_for_parsing)

                if 'error' in resume_data:
                    flash(f"Error parsing resume: {resume_data['error']}", 'error')
                    logger.error(f"Resume parsing error: {resume_data['error']}")
                    return render_template('upload.html') 

                session['parsed_resume_data'] = resume_data 

                resume_summary = generate_resume_summary(resume_data)
                if not resume_summary:
                    flash("Could not generate resume summary.", 'warning')
                    logger.warning("Failed to generate resume summary.")

                matcher = ResumeJobMatcher(model_name="llama3.2")
                
                # --- NEW LOGIC: Query jobs from database instead of real-time scraping ---
                # Fetch jobs posted in the last 7 days from the database
                seven_days_ago = datetime.utcnow() - timedelta(days=7)
                db_job_listings_obj = JobListing.query.filter(JobListing.date_posted >= seven_days_ago).all()
                
                if not db_job_listings_obj:
                    flash('No job listings found in the database for the last 7 days. Please run the background scraper first!', 'warning')
                    return render_template('upload.html', resume_data=resume_data, resume_summary=resume_summary)
                
                # Convert SQLAlchemy objects to dictionaries for the matcher
                job_listings_for_matcher = [job.to_dict() for job in db_job_listings_obj]
                logger.info(f"Retrieved {len(job_listings_for_matcher)} jobs from database for matching.")


                matched_jobs = matcher.match_resume_to_jobs(resume_data, job_listings_for_matcher)

                if not matched_jobs:
                    flash('No suitable job matches found based on your resume. Try refining your resume or check back later for new listings.', 'info')
                    return render_template('upload.html', resume_data=resume_data, resume_summary=resume_summary)

                top_matches = matched_jobs[:5]
                return render_template('upload.html', matched_jobs=top_matches, resume_data=resume_data, resume_summary=resume_summary)

            except Exception as e:
                logger.exception("An unhandled error occurred during upload processing.")
                flash(f"An unexpected error occurred: {str(e)}. Please try again.", 'error')
                return render_template('upload.html', resume_data=resume_data, resume_summary=resume_summary) 
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
        io.BytesIO(json_data.encode('utf-8')), 
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

    rendered_html = render_template('resume_pdf_template.html', resume_data=parsed_resume_data)

    pdf_bytes = io.BytesIO()
    try:
        HTML(string=rendered_html).write_pdf(pdf_bytes)
        pdf_bytes.seek(0) 

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
--- END OF FILE cli4.py ---