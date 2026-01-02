# Job Application Letter Generator

Streamlit app that generates a one-page job application letter using:
- CV (facts only)
- Job description
- Example letter (style only)

It extracts facts from the CV and writes a letter without adding new candidate information.

## Features
- Upload CV, job description, and example letter (PDF or TXT)
- Uses the example letter for tone and structure only
- Extracts recent job stations from the CV
- Summarizes job description (company, role, requirements)
- Verifies the final letter against extracted facts
- Download the final letter as a TXT file

## Requirements
- Python 3.9+
- OpenAI API key

## Install
```bash
pip install streamlit openai pypdf
```

## Run
```bash
streamlit run app.py
```

## Usage
1. Enter your OpenAI API key in the sidebar.
2. Upload:
   - CV (PDF or TXT)
   - Example letter (PDF or TXT)
   - Job description (PDF or TXT) or paste the text
3. Click "Generate Letter".
4. Review:
   - Recent job stations
   - Extracted CV facts
   - Job description summary
5. Download the final letter.

## Notes
- The app enforces "no new info" by extracting explicit CV facts and verifying the output.
- If a job requirement is not supported by the CV, it is not mentioned.
- The API key is only used in the current Streamlit session and is not stored on disk.

## Troubleshooting
- If PDF text looks wrong, try re-exporting the PDF or converting it to TXT first.
- If you see "OpenAI request failed", double-check your API key.
