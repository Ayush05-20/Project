import argparse
import time
import random
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate

# Template for parsing
template = (
    "You are tasked with extracting specific information from the following text content: {dom_content}. "
    "Please follow these instructions carefully: \n\n"
    "1. **Extract Information:** Only extract the information that directly matches the provided description: {parse_description}. "
    "2. **No Extra Content:** Do not include any additional text, comments, or explanations in your response. "
    "3. **Empty Response:** If no information matches the description, return an empty string ('')."
    "4. **Direct Data Only:** Your output should contain only the data that is explicitly requested, with no other text."
)

model = OllamaLLM(model="llama3")

def scrape_website(website):
    print("Setting up Selenium WebDriver...")
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")  # Run in headless mode for CLI
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    service = Service(executable_path="/Users/ayush/CVisionary-AI Based Resume Screener With Job Matching/chromedriver")
    
    try:
        print(f"Navigating to {website}...")
        time.sleep(random.uniform(1, 3))  # Human-like delay before navigating
        driver.get(website)
        
        # Simulate human-like waiting (e.g., for page load or CAPTCHA)
        print("Waiting for page to load...")
        time.sleep(random.uniform(3, 6))  # Random delay to mimic human behavior
        
        print("Scraping page content...")
        html = driver.page_source
        return html
    finally:
        driver.quit()

def extract_body_content(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    body_content = soup.body
    if body_content:
        return str(body_content)
    return ""

def clean_body_content(body_content):
    soup = BeautifulSoup(body_content, "html.parser")
    for script_or_style in soup(["script", "style"]):
        script_or_style.extract()
    
    cleaned_content = soup.get_text(separator="\n")
    cleaned_content = "\n".join(
        line.strip() for line in cleaned_content.splitlines() if line.strip()
    )
    return cleaned_content

def split_dom_content(dom_content, max_length=6000):
    return [
        dom_content[i : i + max_length] for i in range(0, len(dom_content), max_length)
    ]

def parse_with_ollama(dom_chunks, parse_description):
    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | model
    parsed_results = []
    
    for i, chunk in enumerate(dom_chunks, start=1):
        time.sleep(random.uniform(0.5, 2))  # Human-like delay between parsing chunks
        print(f"Parsing batch: {i} of {len(dom_chunks)}")
        response = chain.invoke(
            {"dom_content": chunk, "parse_description": parse_description}
        )
        parsed_results.append(response)
    
    return "\n".join(parsed_results)

def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description="CLI Web Scraper with Selenium and Ollama")
    parser.add_argument("url", help="")
    parser.add_argument("parse_description", help="Description of what to parse from the content")
    args = parser.parse_args()

    # Scrape and process the website
    print("Starting web scraping process...")
    dom_content = scrape_website(args.url)
    body_content = extract_body_content(dom_content)
    cleaned_content = clean_body_content(body_content)
    
    # Split and parse content
    dom_chunks = split_dom_content(cleaned_content)
    print("Parsing content with Ollama...")
    result = parse_with_ollama(dom_chunks, args.parse_description)
    
    # Output results
    print("\nParsed Results:")
    print(result if result else "No matching content found.")

if __name__ == "__main__":
    main()