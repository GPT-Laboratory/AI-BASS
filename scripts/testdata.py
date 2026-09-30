

#!/usr/bin/env python3
"""
Test data initialization script using Admin Backend APIs
Waits for backend to be ready and uses proper authentication
"""
import os
import sys
import time
import requests
from datetime import datetime

# Configuration
ADMIN_API_BASE = os.environ.get("ADMIN_API_BASE", "http://localhost:5000")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "ai-bass-admin")
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
MAX_RETRIES = 30
RETRY_DELAY = 2

def wait_for_service(url: str, service_name: str, max_retries: int = MAX_RETRIES) -> bool:
    """Wait for a service to become ready by checking its health endpoint"""
    print(f"Waiting for {service_name} at {url}...")
    for i in range(max_retries):
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                print(f"✓ {service_name} is ready!")
                return True
        except requests.exceptions.RequestException as e:
            print(f"  Attempt {i+1}/{max_retries}: {service_name} not ready yet ({e.__class__.__name__})")
        time.sleep(RETRY_DELAY)

    print(f"✗ {service_name} failed to become ready after {max_retries} attempts")
    return False

def login_admin() -> str:
    """Login to admin backend and return JWT token"""
    print(f"Logging in as admin to {ADMIN_API_BASE}/login...")
    try:
        response = requests.post(
            f"{ADMIN_API_BASE}/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
            timeout=10
        )
        response.raise_for_status()
        token = response.json()["token"]
        print("✓ Successfully authenticated")
        return token
    except Exception as e:
        print(f"✗ Login failed: {e}")
        sys.exit(1)

def auth_headers(token: str) -> dict:
    """Return authorization headers with JWT token"""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

def check_existing_data(token: str) -> bool:
    """Check if database already has data"""
    try:
        response = requests.get(
            f"{ADMIN_API_BASE}/companies",
            headers=auth_headers(token),
            timeout=10
        )
        response.raise_for_status()
        companies = response.json()
        if companies and len(companies) > 0:
            print("Database already initialized. Skipping test data insert.")
            return True
        return False
    except Exception as e:
        print(f"Warning: Could not check existing data: {e}")
        return False

print("="*60)
print("Test Data Initialization Script")
print("="*60)

# Wait for admin backend to be ready (which depends on lightrag-service)
if not wait_for_service(f"{ADMIN_API_BASE}/health", "Admin Backend"):
    print("✗ Admin Backend is not available. Exiting.")
    sys.exit(1)

# Login and get token
token = login_admin()

# Check if data already exists
if check_existing_data(token):
    sys.exit(0)

print("\nStarting test data insertion...")
print("-"*60)

# Sample company data WITHOUT phone_numbers
sample_companies = [
    {
        "company_id": "FI1111111-1",
        "name": "Example Solar Ltd",
        "basic_info": {
            "industry": "Energy and software",
            "founded": 2018,
            "headquarters": "Espoo"
        }
    },
    {
        "company_id": "FI2222222-2",
        "name": "Example Neuro Ltd",
        "basic_info": {
            "industry": "Health technology",
            "founded": 2020,
            "headquarters": "Tampere"
        }
    },
    {
        "company_id": "FI3333333-3",
        "name": "Example IT Ltd",
        "basic_info": {
            "industry": "IT services",
            "founded": 2015,
            "headquarters": "Turku"
        }
    },
    {
        "company_id": "FI4444444-4",
        "name": "Example Bio Ltd",
        "basic_info": {
            "industry": "Biotechnology",
            "founded": 2012,
            "headquarters": "Helsinki"
        }
    }
]

# Insert companies using API
print("\n1. Creating companies...")
company_id_map = {}
for company in sample_companies:
    try:
        response = requests.post(
            f"{ADMIN_API_BASE}/companies",
            headers=auth_headers(token),
            json=company,
            timeout=20
        )
        response.raise_for_status()
        mongodb_id = response.json()["id"]
        company_id_map[company["company_id"]] = mongodb_id
        print(f"  ✓ Created company: {company['name']} (ID: {mongodb_id})")
    except Exception as e:
        print(f"  ✗ Failed to create company {company['name']}: {e}")
        sys.exit(1)

print(f"  Total companies created: {len(company_id_map)}")

# Metadata content
def now():
    return datetime.utcnow().isoformat()

raw_metadata = [
    ("FI1111111-1", "strategy", "We develop smart solar energy management using IoT technology, aiming for global growth in the green transition."),
    ("FI1111111-1", "personnel", "The company employs 35 people, mainly software developers and energy specialists."),
    ("FI1111111-1", "long_term_goals", "Our goal is to provide an energy-efficient solution to 100,000 households by 2030."),
    ("FI2222222-2", "strategy", "We develop safe and user-friendly neural interfaces connecting the brain and AI."),
    ("FI2222222-2", "business_environment", "We operate in the rapidly developing neurotechnology industry, where regulation and security are key success factors."),
    ("FI3333333-3", "strategy", "We provide local IT support to households and small businesses."),
    ("FI3333333-3", "long_term_goals", "Expand the service network to all regions and develop AI-assisted remote support."),
    ("FI4444444-4", "personnel", "Our research and development team consists of 25 biochemistry specialists working on new biosynthesis techniques."),
    ("FI4444444-4", "business_environment", "Biotechnology is competitive, but we have strong university partnerships and a patent portfolio.")
]

# Insert metadata using API
print("\n2. Creating metadata documents...")
metadata_count = 0
for ext_id, doc_type, content in raw_metadata:
    metadata_doc = {
        "company_id": company_id_map[ext_id],
        "type": doc_type,
        "content": {"description": content},
        "created_at": now(),
        "updated_at": now()
    }
    try:
        response = requests.post(
            f"{ADMIN_API_BASE}/metadata",
            headers=auth_headers(token),
            json=metadata_doc,
            timeout=60
        )
        response.raise_for_status()
        result = response.json()
        metadata_count += 1
        print(f"  ✓ Created {doc_type} for {ext_id} (MongoDB ID: {result['_id']})")
    except Exception as e:
        print(f"  ✗ Failed to create metadata for {ext_id}: {e}")

print(f"  Total metadata documents created: {metadata_count}")

# Sample users linked to company_id
sample_users = [
    {
        "company_id": company_id_map["FI1111111-1"],
        "first_name": "Alex",
        "last_name": "Example",
        "description": "CTO with expertise in renewable energy software solutions.",
        "phone_number": "+12025550101"
    },
    {
        "company_id": company_id_map["FI2222222-2"],
        "first_name": "Robin",
        "last_name": "Example",
        "description": "Neurotechnology engineer and product strategist.",
        "phone_number": "+12025550102"
    },
    {
        "company_id": company_id_map["FI3333333-3"],
        "first_name": "Sam",
        "last_name": "Example",
        "description": "Customer support lead for regional IT services.",
        "phone_number": "+12025550103"
    }
]

# Insert users using API
print("\n3. Creating users...")
user_count = 0
for user in sample_users:
    try:
        response = requests.post(
            f"{ADMIN_API_BASE}/users",
            headers=auth_headers(token),
            json=user,
            timeout=20
        )
        response.raise_for_status()
        user_id = response.json()["id"]
        user_count += 1
        print(f"  ✓ Created user: {user['first_name']} {user['last_name']} (ID: {user_id})")
    except Exception as e:
        print(f"  ✗ Failed to create user {user['first_name']} {user['last_name']}: {e}")

print(f"  Total users created: {user_count}")

# Settings document
settings_doc = {
    "global_system_prompt": (
        """You are AI-BASS, an AI-based operational intelligence and strategy system for micro and startup enterprises (SMEs) in their local markets.
Your purpose: enhance decision-making accuracy, strategic scalability, and sustainable competitiveness of the companies you advice.

Behavioral Rules:
Use precise, domain-relevant terminology. Eliminate filler, speculation, and rhetorical padding.
Never hedge your answers.
For complex requests, define a plan of execution and request missing data before continuing.
Deliver concise, actionable outputs only—no explanatory redundancy or appended commentary.
Focus on utility and clarity. No conjecture, no repetition, no closing statements.
Advisory Directives:
Strategy: Provide direct recommendations on market positioning, growth planning, and competitive differentiation.
Operations: Identify inefficiencies, prioritize corrective measures, and propose process optimizations.
Finance: Support resource allocation, cost management, and investment timing decisions.
Sustainability: Integrate smart green growth principles—energy efficiency, circular economy, sustainable scaling.
Innovation: Connect company strategy to regional RDI networks and applicable innovation ecosystems.
Localization: Ensure all recommendations align with the company's local market, policy, and innovation conditions.
Objective:
Deliver solid, evidence-based strategic counsel that enables SME leaders to make faster, better, and more sustainable decisions in real operational contexts.

Respond using the user language."""
    ),
    "whatsapp_error_message": "Hello, you are not registered in the system.",
    "memory_generation_prompt": """Your Task: Analyze the provided conversation and extract only new, important information about the user or company to be stored as memories.

You will be given the conversation and a list of existing_memories.

Your primary goal is to aggressively filter out any information that is already known or is a restatement of existing company data.

Core Principles

1. DEFAULT TO false: Most conversations will not contain new, memory-worthy information. Your default assumption should be has_important_content: false. Only create memories if a statement meets the strict criteria below.
2. NEW Information ONLY: The memory must be new information not present in the existing_memories list. Do not create duplicates or slight variations of existing memories.
3. USER vs. ASSISTANT:
User Messages: Prioritize new, explicit facts, preferences, goals, or pain points stated by the user. (e.g., "We are expanding to Germany next quarter," "My new point of contact is Jane Doe," "I prefer bulleted summaries.")
Assistant Messages: Be extremely critical of assistant messages. Most of the time, they are summarizing, analyzing, or retrieving existing data (like company strategy, personnel count, file contents). Do not store this.

Strict "DO NOT STORE" Rules

This is the most important part of your task. Failure to follow these rules will resultIn a bad response.

DO NOT STORE facts retrieved by the assistant, even if they seem important. If the assistant states a fact about the company (e.g., "Your revenue was $10M," "Your strategy is X"), it is considered existing information.
DO NOT STORE anything from an assistant message that includes a citation (e.g., [1], [x]). This is a guarantee that it is existing information.
DO NOT STORE summaries of existing data.
DO NOT STORE common conversational fluff (greetings, confirmations like "yes," "okay," "got it").

What TO Store (Good Memories)

New facts from the user: "We just hired a new Head of Marketing."
New preferences/goals from the user: "From now on, please send all reports directly to me."
New problems/pain points from the user: "We've been struggling with our supply chain in Asia."
Rare assistant insights: Only if the assistant generates a completely novel insight or synthesis that is not based on retrieving a stored fact. (e.g., "I've noticed a pattern: your team's project velocity drops 30% when projects last longer than 6 weeks." — This is an analysis, not a retrieval).

Respond with a JSON object.

has_important_content: (boolean) Set to true only if you are adding new, valid memories. Otherwise, false.
memories: (array of strings) The list of new memories. Write memories in the same language as the conversation. Keep them concise.""",
    	"prompt_classification": [
            "Strategic decisions",
            "Tactical decisions",
            "Operational decisions",
            "Innovation-related",
            "Networking-related"
        ],
        "response_classification": [
            "Fact-based support",
            "Action recommendation",
            "Cognitive clarification",
            "Sparring / bringing up alternatives",
            "Normative or critical feedback"
        ],
        "interaction_tone_classification": [
            "Encouraging / positive",
            "Neutral / professional",
            "Critical / challenging",
            "Question-focused",
            "Solution-oriented"
        ],
    "system_prompts": [

    ],
    "predefined_prompts": [
    {
        "name": "What do you know about me and my company?",
        "text": "What do you know about me and my company?"
    },
    {
        "name": "Can you identify any deviations from our strategy in our operations?",
        "text": "Can you identify any deviations from our strategy in our operations?"
    },
    {
        "name": "Can you see any technical risks in our activities?",
        "text": "Can you see any technical risks in our activities?"
    }
]
}

# Insert settings using API
print("\n4. Creating settings...")
try:
    response = requests.put(
        f"{ADMIN_API_BASE}/settings",
        headers=auth_headers(token),
        json=settings_doc,
        timeout=20
    )
    response.raise_for_status()
    print("  ✓ Settings created successfully")
except requests.exceptions.HTTPError as e:
    if e.response.status_code == 409:
        print("  ⚠ Settings already exist, skipping")
    else:
        print(f"  ✗ Failed to create settings: {e}")
except Exception as e:
    print(f"  ✗ Failed to create settings: {e}")

print("\n" + "="*60)
print("Test data initialization completed successfully!")
print("="*60)

