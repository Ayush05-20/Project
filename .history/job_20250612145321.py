import requests
from bs4 import BeautifulSoup
import csv
import sqlite3
import re # For cleaning up text

# --- Simulated HTML Content (This would be fetched from a real URL) ---
# This string represents a simplified HTML page with job listings.
# In a real scenario, you would use requests.get(url).content to get this.
SIMULATED_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Nepal Job Listings</title>
</head>
<body>
    <h1>Job Opportunities in Nepal</h1>

    <div class="job-listing">
        <h2 class="job-title"><a href="https://example.com/jobs/php-dev-classic-tech">Senior PHP Developer</a></h2>
        <p class="company">Classic Tech</p>
        <p class="location">Kathmandu</p>
        <div class="description">
            Responsible for developing new features and functionality, integrating APIs,
            and maintaining existing software in an Agile environment.
        </div>
        <div class="requirements">
            <ul>
                <li>Minimum 4 years experience.</li>
                <li>Strong Core PHP, CodeIgniter, Laravel, MySQL/PostgreSQL.</li>
                <li>Proficiency in HTML, CSS, JavaScript, and front-end frameworks.</li>
                <li>Experience with REST/SOAP APIs, XML/JSON.</li>
                <li>Proficient in Git.</li>
                <li>Excellent communication skills.</li>
            </ul>
        </div>
        <a class="job-url" href="https://example.com/jobs/php-dev-classic-tech">View Details</a>
    </div>

    <div class="job-listing">
        <h2 class="job-title"><a href="https://example.com/jobs/network-engineer-classic">Network Engineer</a></h2>
        <p class="company">Classic Tech</p>
        <p class="location">Kathmandu</p>
        <div class="description">
            Manage and maintain the network infrastructure in an ISP/Telecommunication environment.
            Troubleshoot network issues and ensure high availability.
        </div>
        <div class="requirements">
            <ul>
                <li>Bachelor's degree in Information Technology or relevant experience.</li>
                <li>Minimum 2 years experience in a similar role.</li>
                <li>CCNA/JNCIA certification preferred.</li>
                <li>Knowledge of OSI Model, IP addressing, BGP, MPLS, VPN technologies.</li>
                <li>Experience with Cisco, Juniper, and Mikrotik routers.</li>
            </ul>
        </div>
        <a class="job-url" href="https://example.com/jobs/network-engineer-classic">View Details</a>
    </div>

    <div class="job-listing">
        <h2 class="job-title"><a href="https://example.com/jobs/mern-trainee-uranus">Trainee MERN Stack Developer</a></h2>
        <p class="company">Uranus Tech Nepal Pvt Ltd</p>
        <p class="location">Kathmandu</p>
        <div class="description">
            Entry-level position for aspiring MERN stack developers.
            Opportunity to learn and grow with a dynamic team.
        </div>
        <div class="requirements">
            <ul>
                <li>Foundational knowledge in web development (HTML, CSS, JavaScript).</li>
                <li>Eagerness to learn MongoDB, Express.js, React, Node.js.</li>
                <li>Basic understanding of database concepts.</li>
            </ul>
        </div>
        <a class="job-url" href="https://example.com/jobs/mern-trainee-uranus">View Details</a>
    </div>

    <div class="job-listing">
        <h2 class="job-title"><a href="https://example.com/jobs/corp-sales-classic">Corporate Sales Officer</a></h2>
        <p class="company">Classic Tech</p>
        <p class="location">Kathmandu</p>
        <div class="description">
            Responsible for achieving sales targets, customer satisfaction, and building client relationships.
            Focus on corporate clients for internet and related services.
        </div>
        <div class="requirements">
            <ul>
                <li>2+ years experience in a sales or marketing role.</li>
                <li>Strong communication and negotiation skills.</li>
                <li>Proficiency in MS Office (Excel, Word, PowerPoint).</li>
                <li>Bachelor's Degree in Marketing or related field preferred.</li>
                <li>Valid driving license and a two-wheeler preferred.</li>
            </ul>
        </div>
        <a class="job-url" href="https://example.com/jobs/corp-sales-classic">View Details</a>
    </div>

</body>
</html>
"""

def clean_text(text):
    """Removes extra whitespace and cleans up text."""
    if text:
        text = re.sub(r'\s+', ' ', text).strip()
    return text

def scrape_job_data_from_html(html_content):
    """
    Parses the provided HTML content to extract job details.
    This is the core "actual scraping logic" for a specific HTML structure.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    job_listings = []

    # Find all div elements that represent a job listing
    for job_div in soup.find_all('div', class_='job-listing'):
        title_tag = job_div.find('h2', class_='job-title')
        company_tag = job_div.find('p', class_='company')
        location_tag = job_div.find('p', class_='location')
        description_tag = job_div.find('div', class_='description')
        requirements_tag = job_div.find('div', class_='requirements')
        url_tag = job_div.find('a', class_='job-url') # Assuming the URL is also specifically linked

        title = clean_text(title_tag.text) if title_tag else 'N/A'
        company = clean_text(company_tag.text) if company_tag else 'N/A'
        location = clean_text(location_tag.text) if location_tag else 'N/A'
        description = clean_text(description_tag.text) if description_tag else 'N/A'
        requirements = clean_text(requirements_tag.text) if requirements_tag else 'N/A'
        
        # Get the href attribute for the URL
        url = url_tag['href'] if url_tag and 'href' in url_tag.attrs else 'N/A'

        job_listings.append({
            'title': title,
            'company': company,
            'location': location,
            'description': description,
            'requirements': requirements,
            'url': url
        })
    return job_listings

# --- Database Storage (SQLite Example) ---

DATABASE_NAME = 'nepal_jobs.db'

def create_db_table():
    """Creates a SQLite database and jobs table if they don't exist."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            company TEXT,
            location TEXT,
            description TEXT,
            requirements TEXT,
            url TEXT UNIQUE
        )
    ''')
    conn.commit()
    conn.close()
    print(f"Database '{DATABASE_NAME}' and table 'jobs' ensured.")

def insert_jobs_to_db(jobs_data):
    """Inserts a list of job dictionaries into the SQLite database."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    inserted_count = 0
    for job in jobs_data:
        try:
            cursor.execute('''
                INSERT INTO jobs (title, company, location, description, requirements, url)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (job['title'], job['company'], job['location'], 
                  job['description'], job['requirements'], job['url']))
            inserted_count += 1
        except sqlite3.IntegrityError:
            print(f"Skipping duplicate job (URL: {job['url']}).")
        except Exception as e:
            print(f"Error inserting job {job.get('title', 'N/A')}: {e}")
            
    conn.commit()
    conn.close()
    print(f"Successfully inserted {inserted_count} jobs into the database.")

# --- CSV Storage ---

CSV_FILE_NAME = 'nepal_jobs.csv'

def save_jobs_to_csv(jobs_data):
    """Saves a list of job dictionaries to a CSV file."""
    if not jobs_data:
        print("No job data to save to CSV.")
        return

    # Define headers based on the dictionary keys
    fieldnames = ['title', 'company', 'location', 'description', 'requirements', 'url']

    with open(CSV_FILE_NAME, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(jobs_data)
    print(f"Successfully saved {len(jobs_data)} jobs to '{CSV_FILE_NAME}'.")

# --- Main Execution ---

if __name__ == "__main__":
    print("--- Starting Job Data Processing ---")

    # Step 1: Get job data using the actual scraping logic on simulated HTML
    # In a real scenario, you would replace SIMULATED_HTML with:
    # response = requests.get("http://your-target-job-portal.com/jobs")
    # html_content = response.content
    # job_listings = scrape_job_data_from_html(html_content)

    job_listings = scrape_job_data_from_html(SIMULATED_HTML)
    
    if job_listings:
        print("\n--- Extracted Job Listings ---")
        for i, job in enumerate(job_listings):
            print(f"Job {i+1}: {job['title']} at {job['company']} ({job['location']}) - {job['url']}")

        # Step 2: Store in Database
        print("\n--- Storing to Database ---")
        create_db_table()
        insert_jobs_to_db(job_listings)

        # Step 3: Store in CSV
        print("\n--- Saving to CSV ---")
        save_jobs_to_csv(job_listings)
    else:
        print("No job listings found or extracted.")
    
    print("\n--- Job Data Processing Complete ---")