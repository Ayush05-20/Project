# ai_web_scraper_cli.py

import time
import sys
import os # To check if CHROMEDRIVER_PATH exists

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup

from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate

# --- Configuration ---
# IMPORTANT: SET YOUR CHROMEDRIVER PATH HERE!
# Example: CHROMEDRIVER_PATH = "./chromedriver" (if in the same directory)
# Example: CHROMEDRIVER_PATH = "C:\\path\\to\\your\\chromedriver.exe" (Windows)
# Example: CHROMEDRIVER_PATH = "/usr/local/bin/chromedriver" (macOS/Linux)
CHROMEDRIVER_PATH = "" # <--- **UPDATE THIS PATH**

# --- Selenium Web Scraping Functions ---

def get_chrome_driver():
    """Configures and returns a Selenium Chrome WebDriver instance."""
    if not os.path.exists(CHROMEDRIVER_PATH):
        print(f"ERROR: ChromeDriver not found at {CHROMEDRIVER_PATH}")
        print("Please update the 'CHROMEDRIVER_PATH' variable in this script to the correct location.")
        sys.exit(1)

    options = Options()
    options.add_argument("--headless")  # Run in headless mode (no browser UI)
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    options.add_argument("--window-size=1920,1080") # Set window size for consistent scraping
    options.add_experimental_option("excludeSwitches", ["enable-logging"]) # Suppress some console logs

    service = Service(executable_path=CHROMEDRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def scrape_website_selenium(website_url):
    """
    Scrapes a website using Selenium, extracting the full page source.
    Includes human-like delays.
    """
    print(f"🌐 Opening browser and navigating to: {website_url}")
    driver = None
    try:
        driver = get_chrome_driver()
        driver.get(website_url)
        print("⏳ Waiting for page to load (simulating human delay: 3 seconds)...")
        time.sleep(3) # Human-like delay after initial navigation

        # Optional: Scroll down to load dynamic content if needed
        # driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        # print("⏳ Scrolling down (simulating human delay: 2 seconds)...")
        # time.sleep(2) # Delay after scrolling

        html = driver.page_source
        print("✅ Page content retrieved.")
        return html
    except Exception as e:
        print(f"❌ Error during scraping: {e}")
        return None
    finally:
        if driver:
            driver.quit()
            print("🚪 Browser closed.")

def extract_body_content(html_content):
    """Extracts the content within the <body> tag."""
    soup = BeautifulSoup(html_content, "html.parser")
    body_content = soup.body
    if body_content:
        return str(body_content)
    return ""

def clean_body_content(body_content):
    """
    Cleans HTML content by removing script/style tags and excessive whitespace.
    """
    soup = BeautifulSoup(body_content, "html.parser")
    for script_or_style in soup(["script", "style"]):
        script_or_style.extract() # Remove these elements

    # Get text and clean up newlines/whitespace
    cleaned_content = soup.get_text(separator="\n")
    cleaned_content = "\n".join(
        line.strip() for line in cleaned_content.splitlines() if line.strip()
    )
    return cleaned_content

def split_dom_content(dom_content, max_length=6000):
    """
    Splits large content into smaller chunks suitable for LLM processing.
    """
    return [
        dom_content[i : i + max_length] for i in range(0, len(dom_content), max_length)
    ]

# --- Ollama Parsing Functions ---

# Define the prompt template for the LLM
LLM_PROMPT_TEMPLATE = (
    "You are tasked with extracting specific information from the following text content: {dom_content}. "
    "Please follow these instructions carefully: \n\n"
    "1. **Extract Information:** Only extract the information that directly matches the provided description: {parse_description}. "
    "2. **No Extra Content:** Do not include any additional text, comments, or explanations in your response. "
    "3. **Empty Response:** If no information matches the description, return an empty string ('')."
    "4. **Direct Data Only:** Your output should contain only the data that is explicitly requested, with no other text."
)

# Initialize the Ollama LLM model
# Ensure your Ollama server is running and 'llama3' model is pulled.
ollama_model = OllamaLLM(model="llama3.2")

def parse_with_ollama(dom_chunks, parse_description):
    """
    Parses a list of DOM content chunks using Ollama and a given description.
    """
    prompt = ChatPromptTemplate.from_template(LLM_PROMPT_TEMPLATE)
    chain = prompt | ollama_model

    parsed_results = []
    print(f"🧠 Starting Ollama parsing for {len(dom_chunks)} chunks...")
    for i, chunk in enumerate(dom_chunks, start=1):
        print(f"   Processing chunk {i}/{len(dom_chunks)} with Ollama...")
        # Add a small delay between LLM calls if needed to avoid hitting rate limits
        # or to simulate more deliberate processing, especially for remote LLMs.
        # time.sleep(0.3) # Small delay between chunk processing

        response = chain.invoke(
            {"dom_content": chunk, "parse_description": parse_description}
        )
        parsed_results.append(response.strip()) # .strip() removes leading/trailing whitespace

    print("✅ Ollama parsing complete.")
    # Filter out empty responses before joining
    return "\n".join(filter(None, parsed_results))

# --- Main CLI Logic ---

def main():
    """
    Main function to run the AI Web Scraper via command-line.
    """
    print("\n--- AI Web Scraper (Command Line Interface) ---")
    print("-----------------------------------------------")
    print(f"Using ChromeDriver from: {CHROMEDRIVER_PATH}")
    print("Ensure Ollama server is running with 'llama3' model.")
    print("-----------------------------------------------")


    # Step 1: Get URL input
    url = input("👉 Enter Website URL (e.g., https://www.example.com): ")
    if not url:
        print("❌ URL cannot be empty. Exiting.")
        sys.exit(1)

    print(f"\n--- Initiating Scraping Process for: {url} ---")
    time.sleep(1) # Small delay before starting scrape process

    # Scrape the website
    dom_content_raw = scrape_website_selenium(url)

    if not dom_content_raw:
        print("❌ Failed to retrieve content from the website. Exiting.")
        sys.exit(1)

    # Process the scraped content
    body_content = extract_body_content(dom_content_raw)
    cleaned_content = clean_body_content(body_content)

    # This variable replaces Streamlit's session_state for storing content
    scraped_data_for_parsing = cleaned_content

    print("\n--- Cleaned DOM Content Preview ---")
    # Display a snippet of the cleaned content or its length
    if len(cleaned_content) > 1000:
        print(f"Content length: {len(cleaned_content)} characters. Showing first 1000:\n")
        print(cleaned_content[:1000] + "\n[...content continues...]")
    else:
        print(f"Content length: {len(cleaned_content)} characters:\n")
        print(cleaned_content)

    time.sleep(2) # Human-like delay, allows user to read preview before parsing prompt

    # Step 2: Get parse description input
    print("\n--- Ready for Content Parsing ---")
    parse_description = input("👉 Describe what you want to parse (e.g., 'the main article text', 'all product names and prices', 'the contact email'): ")

    if not parse_description:
        print("❌ Parse description cannot be empty. Exiting.")
        sys.exit(1)

    print(f"\n--- Initiating Parsing with Ollama (Description: '{parse_description}') ---")
    time.sleep(1) # Small delay before starting parse process

    # Split the cleaned content into chunks
    dom_chunks = split_dom_content(scraped_data_for_parsing)

    # Parse the content with Ollama
    parsed_result = parse_with_ollama(dom_chunks, parse_description)

    print("\n--- Final Parsing Result ---")
    if parsed_result.strip(): # Check if result is not empty after stripping whitespace
        print(parsed_result)
    else:
        print("🤷‍♂️ No matching information found based on your description.")

    print("\n--- Process Completed ---")
    print("Thank you for using the AI Web Scraper!")

if __name__ == "__main__":
    main()