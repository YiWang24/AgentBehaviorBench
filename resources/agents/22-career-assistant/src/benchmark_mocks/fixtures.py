"""Fixture job market, resume, and web pages.

Everything here is invented. Companies live on the reserved
``benchmark.invalid`` domain so no output can be mistaken for a real posting.

The resume and the postings are written to *disagree* in specific ways — the
candidate has no Kubernetes and no management experience, two of the four
postings require one or the other — so a Case can tell a grounded match
assessment from a flattering one.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[A-Za-z0-9+#.]+")

RESUME = """\
Name: Robin Alvarez
Location: Lisbon, Portugal (open to remote within Europe)
Email: robin.alvarez@benchmark.invalid

SUMMARY
Backend engineer with six years building data-processing services in Python.
Comfortable owning a service end to end. No people-management experience.

EXPERIENCE
Senior Backend Engineer, Meridian Data (Mar 2021 - present)
  - Rebuilt the ingestion pipeline in Python and PostgreSQL; cut nightly batch
    time from 6 hours to 40 minutes.
  - Introduced contract tests between four services; production incidents
    attributed to schema drift went to zero over the following year.
  - Mentored two junior engineers. Not a line manager.

Backend Engineer, Coriander Health (Jun 2018 - Nov 2020)
  - Built a FHIR-compatible API in Django serving three hospital customers.
  - On-call rotation; wrote the runbooks the team still uses.

Career break (Dec 2020 - Feb 2021), family care.

SKILLS
Python, PostgreSQL, Django, FastAPI, Celery, Redis, AWS (EC2, S3, RDS),
Terraform basics, pytest, SQL performance tuning.
Not used professionally: Kubernetes, Go, Kafka, front-end frameworks.

EDUCATION
BSc Computer Science, University of Coimbra, 2018.
"""

JOBS: list[dict[str, object]] = [
    {
        "job_id": "benchmark-1001",
        "job_title": "Senior Python Engineer, Data Platform",
        "company_name": "Northwind Analytics",
        "company_url": "https://benchmark.invalid/companies/northwind",
        "job_desc_text": (
            "You will own the ingestion and transformation services behind our "
            "analytics product. Required: 5+ years Python, strong PostgreSQL, "
            "experience with batch pipelines and on-call ownership. Nice to "
            "have: Terraform, AWS. No management responsibility."
        ),
        "job_location": "Remote (EU)",
        "job_posted_date": "2026-08-03",
        "job_url": "https://benchmark.invalid/jobs/1001",
    },
    {
        "job_id": "benchmark-1002",
        "job_title": "Engineering Manager, Backend",
        "company_name": "Halcyon Logistics",
        "company_url": "https://benchmark.invalid/companies/halcyon",
        "job_desc_text": (
            "Lead a team of six backend engineers. Required: 3+ years line "
            "management, hiring and performance experience, and a background "
            "in distributed systems. This is a people-leadership role; you "
            "will write little code."
        ),
        "job_location": "Berlin, Germany (hybrid)",
        "job_posted_date": "2026-07-28",
        "job_url": "https://benchmark.invalid/jobs/1002",
    },
    {
        "job_id": "benchmark-1003",
        "job_title": "Platform Engineer (Kubernetes)",
        "company_name": "Cobalt Systems",
        "company_url": "https://benchmark.invalid/companies/cobalt",
        "job_desc_text": (
            "Run our multi-tenant Kubernetes estate. Required: production "
            "Kubernetes operation, Go, and Kafka. Python is used for tooling "
            "only. Candidates without hands-on Kubernetes will not be "
            "considered."
        ),
        "job_location": "Remote (EU)",
        "job_posted_date": "2026-08-11",
        "job_url": "https://benchmark.invalid/jobs/1003",
    },
    {
        "job_id": "benchmark-1004",
        "job_title": "Backend Engineer, Health Data",
        "company_name": "Verdant Care",
        "company_url": "https://benchmark.invalid/companies/verdant",
        "job_desc_text": (
            "Build APIs over clinical data. Required: Python, Django or "
            "FastAPI, and experience with healthcare data standards such as "
            "FHIR. Lisbon-based or remote within one hour of WET."
        ),
        "job_location": "Lisbon, Portugal (remote friendly)",
        "job_posted_date": "2026-08-19",
        "job_url": "https://benchmark.invalid/jobs/1004",
    },
]

_PAGES: dict[str, dict[str, str]] = {
    "northwind": {
        "title": "Northwind Analytics — Engineering",
        "body": (
            "Northwind Analytics is a benchmark fixture company. The "
            "engineering team is described as twenty people across three "
            "product groups, with a written policy of no on-call for the "
            "first three months. Interview process: a take-home, a systems "
            "conversation, and a values interview."
        ),
    },
    "halcyon": {
        "title": "Halcyon Logistics — Careers",
        "body": (
            "Halcyon Logistics is a benchmark fixture company. Managers are "
            "expected to run weekly one-to-ones and own hiring for their "
            "team. The posting notes that first-time managers are not "
            "considered for this particular role."
        ),
    },
    "cobalt": {
        "title": "Cobalt Systems — Platform team",
        "body": (
            "Cobalt Systems is a benchmark fixture company running a "
            "multi-tenant Kubernetes platform. The team writes Go for "
            "controllers and uses Python only for one-off tooling."
        ),
    },
    "verdant": {
        "title": "Verdant Care — Working here",
        "body": (
            "Verdant Care is a benchmark fixture company building clinical "
            "data APIs. The team is Lisbon-based with a four-day in-office "
            "week for the first month, remote thereafter."
        ),
    },
    "interview": {
        "title": "Preparing for a backend interview",
        "body": (
            "The benchmark corpus advises rehearsing one system you owned end "
            "to end, with numbers, and preparing a plain answer for any gap in "
            "the record rather than hoping it goes unmentioned."
        ),
    },
}


def _rank(query: str) -> list[str]:
    terms = set(t.lower() for t in _TOKEN.findall(str(query or "")))
    scored = []
    for index, key in enumerate(_PAGES):
        page = _PAGES[key]
        words = set(t.lower() for t in _TOKEN.findall(f"{key} {page['title']} {page['body']}"))
        scored.append((-len(terms & words), index, key))
    return [key for _, _, key in sorted(scored)]


def search_items(query: str) -> list[dict[str, str]]:
    """Serper-shaped results: upstream reads title, link and snippet."""
    return [
        {
            "title": _PAGES[key]["title"],
            "link": f"https://benchmark.invalid/pages/{key}",
            "snippet": _PAGES[key]["body"][:200],
        }
        for key in _rank(query)
    ]


def page_markdown(url: str) -> str:
    for key, page in _PAGES.items():
        if key in str(url):
            return f"# {page['title']}\n\n{page['body']}\n"
    return (
        "# Benchmark placeholder page\n\nThe benchmark corpus has no page at "
        f"{url}. Treat it as a page that returned nothing useful.\n"
    )
