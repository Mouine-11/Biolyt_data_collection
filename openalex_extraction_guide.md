# OpenAlex Medical & Life Sciences Data Extraction Guidelines

**To:** Intern  
**From:** Biolyt Data Engineering Team  
**Subject:** Technical Guide for Harvesting Medical & Life Sciences Data from OpenAlex  

---

## 1. Executive Summary & Core Strategy

When extracting data from OpenAlex (https://openalex.org) for biomedical research, **you must use a "Works-Centric" extraction strategy**. 

Do not attempt to scrape or crawl the `/authors` or `/institutions` API endpoints independently. Instead, query the `/works` (publications) endpoint using specific field filters, and extract all relevant data (authors, institutions, sources, funders, and reconstructed abstracts) directly into **a single flat CSV dataset**.

```
[ Works API Endpoint ] (Filtered by Combined Fields: 13|24|27|30|35|36)
         │
         └───> Extract & flatten all publication details, authors, 
               institutions, sources, and abstracts into a single file:
               
               ==> openalex_works.csv
```

---

## 2. Why We Must Focus on "Works" (Core Constraints)

OpenAlex is a global Scholarly Graph containing millions of records. Filtering it specifically for our target fields is only possible through the `/works` endpoint due to API limitations:

### A. Non-Works Endpoints Lack Subject Filters
The OpenAlex endpoints for authors (`/authors`) and institutions (`/institutions`) **do not support academic domain or topic filters**. You cannot query the `/authors` API to "return only medical/biological researchers."
*   If you crawled `/authors` directly, you would download **115+ million profiles**, including art historians, theoretical physicists, and musicians.
*   If you crawled `/institutions` directly, you would download **100,000+ organizations** (e.g. agricultural colleges, astronomy labs).

### B. Subject Affiliation is Contextual
An author or institution is only considered relevant to our research because they publish papers in our target fields. Therefore, we must establish the boundaries first using publication metadata, and then map back to the associated entities.

---

## 3. How to Filter for Medical & Biological Data

OpenAlex categorizes fields under a strict taxonomy. To get a complete dataset covering clinical medicine and foundational laboratory sciences, we must target specific **Field IDs** across two separate domains:

### A. Understanding the Taxonomy Division
OpenAlex separates clinical medical practice from basic biological sciences:
*   **Domain: Health Sciences (ID 4):** Covers applied, clinical health fields (e.g. Medicine, Dentistry).
*   **Domain: Life Sciences (No Domain filter for this combination):** Covers basic biological and laboratory sciences (e.g. Biochemistry, Immunology, Pharmacology).

Because of this division, using the default Domain filter `domain.id:4` (Health Sciences) **excludes** basic science research like biochemistry. We must bypass the domain level and filter directly using individual **Field IDs**.

### B. Target Field IDs
We target these 6 specific Field IDs:
1.  **`27`** - Medicine (Clinical Medicine, Surgery, Disease Studies)
2.  **`35`** - Dentistry (Oral Health & Surgery)
3.  **`36`** - Health Professions (Therapies, Occupational Health, Radiography)
4.  **`13`** - Biochemistry, Genetics, and Molecular Biology
5.  **`24`** - Immunology and Microbiology
6.  **`30`** - Pharmacology, Toxicology, and Pharmaceutics

### C. Combined Filter String
To harvest all of these fields together in a single API query, combine the IDs with the **`|` (OR)** operator:
**`13|24|27|30|35|36`**

---

## 4. The Output CSV Schema (Single Flat Table)

Our harvester consolidates all data into **exactly one flat file** (`openalex_works.csv`). To represent relational details inside a single row, multi-valued items (like authors or institutions) are represented as semicolon-separated strings.

This makes the dataset easy to open directly in Microsoft Excel, Google Sheets, or Python (using Pandas).

### CSV Column Definitions
1.  **`openalex_id`:** Unique identifier for the publication.
2.  **`doi`:** Digital Object Identifier URL link.
3.  **`title`:** Title of the paper.
4.  **`publication_year`:** Year of publication (integer).
5.  **`publication_date`:** Exact date of publication (YYYY-MM-DD).
6.  **`type`:** Type of document (e.g. `article`, `book-chapter`).
7.  **`language`:** ISO code of the article language (e.g. `en`).
8.  **`journal_name`:** Name of the hosting journal or venue.
9.  **`publisher`:** The publishing company/society.
10. **`issn`:** Journal ISSN.
11. **`is_oa`:** True if open-access is available.
12. **`oa_status`:** OA type (e.g. `gold`, `green`, `hybrid`, `bronze`).
13. **`oa_url`:** Direct link to the open access full-text article/PDF.
14. **`authors`:** List of all author names, separated by semicolons.
15. **`first_author_institution`:** Main affiliation of the primary author.
16. **`institutions`:** Unique list of all institutions involved in the paper, separated by semicolons.
17. **`countries`:** Unique list of all country codes involved, separated by semicolons.
18. **`cited_by_count`:** Total citations count.
19. **`primary_topic`:** Categorized primary research topic name.
20. **`primary_topic_field`:** Academic Field name (e.g. `Medicine`).
21. **`primary_topic_domain`:** Academic Domain name (e.g. `Health Sciences`).
22. **`mesh_terms`:** List of all Medical Subject Headings (MeSH), separated by semicolons.
23. **`major_mesh_terms`:** List of major MeSH topics only, separated by semicolons.
24. **`funders`:** Semicolon-separated list of funding organizations.
25. **`abstract`:** Reconstructed full-text abstract narrative.
26. **`updated_date`:** Last modified timestamp on OpenAlex.

---

## 5. Critical API Implementation Rules

When writing your harvesting script, you must adhere to the following OpenAlex API rules:

### A. Use Cursor-Based Pagination
*   Standard offset pagination (`?page=X`) is capped at a total of 10,000 results.
*   To harvest the complete database, you must use **cursor pagination**. Start by appending `cursor=*` to your first API request. The API response will return a token named `meta.next_cursor`. Pass this token as the `cursor` argument for the next page request, repeating until the results are exhausted.

### B. Handle the Inverted Index for Abstracts
*   For copyright reasons, OpenAlex does not return plaintext abstracts. Instead, they return an `abstract_inverted_index` where words are keys and their positions are lists of integers: `{"OpenAlex": [0], "is": [1], "great": [2]}`.
*   Your script must reconstruct the text by sorting words based on their index positions.

### C. Authenticate & Respect Rate Limits
*   OpenAlex requires an API key for high-volume downloading. Register a free account at [openalex.org](https://openalex.org) to obtain your key, and append it as `api_key=YOUR_KEY` to requests.
*   The free key gives you a budget of **100,000 credits/day** (about 10,000 page requests).
*   If you hit a `429 Too Many Requests` or `5xx` error, implement exponential backoff sleep cycles to avoid getting blocked.

### D. Progress Checkpointing (Resumability)
*   Because downloads take time, your script must log the current `next_cursor` state of active crawls to a tracking file (e.g. `openalex_progress.json`) in real-time. If the script collapses, it must load the last saved cursor and resume without starting over.

---

## 6. Pre-built Reference Implementation

A reference script implementing all of these guidelines (including multithreading, cursor resuming, single flat CSV consolidation, abstract reconstruction, and rate-limit backoff) has been built and placed at the root of the workspace:
*   [openalex_downloader.py](file:///c:/Users/LeMonde/Desktop/Biolyt_Inter/Biolyt_data_collection/openalex_downloader.py)

### Main Target Execution Command:

To download **all** available publications from the year **2010 to 2026** for our target fields (Medicine, Dentistry, Health Professions, Biochemistry, Immunology, and Pharmacology), use the following concurrent command:

```powershell
python openalex_downloader.py --field-id "13|24|27|30|35|36" --start-year 2010 --end-year 2026 --threads 5
```

*   **`--field-id "13|24|27|30|35|36"`:** Instructs the harvester to pull the targeted medical and biological fields.
*   **`--start-year 2010 --end-year 2026`:** Slices the search range to capture the exact timeframe.
*   **`--threads 5`:** Spawns 5 parallel threads (one per partition) to download concurrently and save time.
*   *(Omit the `--limit` flag to ensure that the script runs until all records are successfully extracted).*
