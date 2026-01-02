import json
import logging
import re
import warnings
from io import BytesIO

import streamlit as st
from openai import OpenAI
from pypdf import PdfReader
from pypdf.errors import PdfReadWarning

warnings.filterwarnings("ignore", category=PdfReadWarning)
logging.getLogger("pypdf").setLevel(logging.ERROR)
logging.getLogger("PyPDF2").setLevel(logging.ERROR)
logging.getLogger(__name__).setLevel(logging.INFO)


def read_pdf_bytes(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    texts = []
    for page in reader.pages:
        text = page.extract_text() or ""
        texts.append(text)
    return "\n".join(texts).strip()


def read_uploaded(uploaded_file) -> str:
    if uploaded_file is None:
        return ""
    data = uploaded_file.getvalue()
    name = (uploaded_file.name or "").lower()
    if name.endswith(".pdf"):
        return read_pdf_bytes(data)
    try:
        return data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="ignore").strip()


def pick_input(text_value: str, file_value) -> str:
    if text_value and text_value.strip():
        return text_value.strip()
    return read_uploaded(file_value)


def chat(client: OpenAI, model: str, system: str, user: str, temperature: float = 0.0) -> str:
    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).error("OpenAI API error: %s", type(exc).__name__)
        st.error("OpenAI request failed. Check your API key and try again.")
        st.stop()


def excerpt_bullets(text: str, limit: int = 500) -> str:
    if not text:
        return "- [empty]"
    raw = text.strip()
    snippet = raw[:limit]
    if len(raw) > limit:
        cut = snippet.rfind(" ")
        if cut > 0:
            snippet = snippet[:cut] + "..."
        else:
            snippet = snippet + "..."
    snippet = re.sub(r"[\u2022\u00b7\u2027\u25aa\u25cf]", "\n", snippet)
    snippet = re.sub(r"\s+-\s+", "\n", snippet)
    lines = [line.strip() for line in snippet.splitlines() if line.strip()]
    if not lines:
        lines = [snippet]
    expanded = []
    for line in lines:
        parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", line) if p.strip()]
        expanded.extend(parts if parts else [line])
    if len(expanded) == 1 and len(expanded[0]) > 140:
        chunks = []
        line = expanded[0]
        while line:
            if len(line) <= 120:
                chunks.append(line)
                break
            cut = line.rfind(" ", 0, 121)
            if cut <= 0:
                cut = 120
            chunks.append(line[:cut].strip())
            line = line[cut:].strip()
        expanded = chunks
    return "\n".join(f"- {line}" for line in expanded)


def normalize_requirements(reqs) -> list[str]:
    if isinstance(reqs, list):
        items = reqs
    elif isinstance(reqs, str):
        items = reqs.splitlines()
    else:
        items = []
    cleaned = []
    for item in items:
        text = item.strip()
        if not text:
            continue
        text = re.sub(r"^[\-\u2022\u00b7\u2027\u25aa\u25cf]\s*", "", text)
        cleaned.append(text)
    return cleaned


def parse_jd_summary(text: str) -> dict | None:
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


def fallback_requirements(text: str, limit: int = 10) -> list[str]:
    if not text:
        return []
    lines = []
    for raw in text.splitlines():
        line = raw.strip().strip(",")
        if not line or line in {"{", "}", "[", "]"}:
            continue
        line = line.strip('"')
        line = re.sub(r'^(company_name|role_title|requirements)\s*:\s*', '', line, flags=re.I)
        if line:
            lines.append(line)
    return lines[:limit]


st.set_page_config(page_title="Job Letter Generator", page_icon="📝", layout="centered")
st.title("Job Application Letter Generator")
st.write(
    "Upload your CV, a sample application letter (style only), and a job description. "
    "The app extracts facts from the CV and writes a one-page letter without adding new info."
)

st.sidebar.title("Settings")
api_key = st.sidebar.text_input(
    "OpenAI API Key", type="password", help="Stored only in this session."
)
model = st.sidebar.selectbox("Model", ["gpt-4o-mini"], index=0)
st.sidebar.subheader("Inputs")
cv_file = st.sidebar.file_uploader("CV (PDF or TXT)", type=["pdf", "txt"])

letter_file = st.sidebar.file_uploader("Example letter (PDF or TXT)", type=["pdf", "txt"])

jd_file = st.sidebar.file_uploader("Job description (PDF or TXT)", type=["pdf", "txt"])
jd_text = st.sidebar.text_area("Or paste job description text", height=120)

if "final_letter" not in st.session_state:
    st.session_state.final_letter = ""
if "facts_block" not in st.session_state:
    st.session_state.facts_block = ""
if "recent_jobs" not in st.session_state:
    st.session_state.recent_jobs = []
if "jd_summary" not in st.session_state:
    st.session_state.jd_summary = {}

generate = st.button("Generate Letter")

if generate:
    if not api_key:
        st.error("Please provide your OpenAI API key.")
        st.stop()

    cv_input = pick_input("", cv_file)
    jd_input = pick_input(jd_text, jd_file)
    letter_input = pick_input("", letter_file)

    if not cv_input:
        st.error("CV input is empty.")
        st.stop()
    if not jd_input:
        st.error("Job description input is empty.")
        st.stop()

    client = OpenAI(api_key=api_key)

    with st.spinner("Extracting job description summary..."):
        jd_system = "You extract structured info from a job description."
        jd_user = (
            "Return JSON with keys: company_name, role_title, requirements.\n"
            "Requirements must be a list of short strings, only what is explicitly in the JD.\n\n"
            f"JD:\n{jd_input}\n"
        )
        jd_json_text = chat(client, model, jd_system, jd_user, temperature=0.0)
        jd_summary = parse_jd_summary(jd_json_text)
        if jd_summary is None:
            jd_summary = {"requirements": fallback_requirements(jd_json_text)}

    with st.spinner("Extracting CV facts..."):
        facts_system = "You extract factual statements from a CV."
        facts_user = (
            "Extract only explicit facts from the CV text. Do not infer, generalize, or add info.\n"
            "Return a bullet list. Each bullet should be one short fact and must be present in the CV text.\n\n"
            f"CV:\n{cv_input}\n"
        )
        facts_text = chat(client, model, facts_system, facts_user, temperature=0.0)
        facts = [
            line[2:].strip()
            for line in facts_text.splitlines()
            if line.strip().startswith("- ")
        ]

    if not facts:
        st.error("No facts extracted. Check the CV input or try a different file.")
        st.stop()

    facts_block = "\n".join("- " + f for f in facts)

    with st.spinner("Extracting recent job stations..."):
        jobs_system = "You extract recent job stations from a CV."
        jobs_user = (
            "Extract up to 3 most recent job stations from the CV.\n"
            "Return a bullet list with one station per bullet in this format:\n"
            "YYYY–YYYY | Role | Company\n"
            "Only use explicit info from the CV. If a field is missing, omit it.\n\n"
            f"CV:\n{cv_input}\n"
        )
        jobs_text = chat(client, model, jobs_system, jobs_user, temperature=0.0)
        recent_jobs = [
            line[2:].strip()
            for line in jobs_text.splitlines()
            if line.strip().startswith("- ")
        ]

    example_block = letter_input if letter_input else "[none]"

    with st.spinner("Drafting letter..."):
        letter_system = "You write job application letters using only provided facts."
        letter_user = (
            "Write a one-page job application letter (about 250-350 words).\n\n"
            "Constraints:\n"
            "- Use ONLY candidate facts from FACTS.\n"
            "- Do NOT add any new candidate information, dates, skills, or claims not in FACTS.\n"
            "- It is OK to mention the company name and role from the job description.\n"
            "- If a requirement from the job description is not supported by FACTS, do not mention it.\n"
            "- Use more recent FACTS rather than older ones.\n"
            "- Use the name of the contact person in the greeting, if available.\n"
            "- Use the example letter ONLY for tone/structure, not for facts.\n"
            "- Output plain text, no markdown.\n\n"
            f"JOB DESCRIPTION:\n{jd_input}\n\n"
            f"FACTS:\n{facts_block}\n\n"
            f"EXAMPLE LETTER (style only):\n{example_block}\n"
        )
        draft_letter = chat(client, model, letter_system, letter_user, temperature=0.2)

    with st.spinner("Verifying facts..."):
        verify_system = "You are a strict factual editor."
        verify_user = (
            "Remove or rewrite any sentence that introduces candidate info not present in FACTS.\n"
            "If a sentence cannot be fully supported by FACTS, delete it.\n"
            "Return only the revised letter as plain text.\n\n"
            f"FACTS:\n{facts_block}\n\n"
            f"LETTER:\n{draft_letter}\n"
        )
        final_letter = chat(client, model, verify_system, verify_user, temperature=0.0)

    st.session_state.final_letter = final_letter
    st.session_state.facts_block = facts_block
    st.session_state.recent_jobs = recent_jobs
    st.session_state.jd_summary = jd_summary

if st.session_state.final_letter:
    st.subheader("CV Information")
    if st.session_state.recent_jobs:
        st.markdown("\n".join(f"- {job}" for job in st.session_state.recent_jobs))
    else:
        st.markdown("- [not found]")
    st.markdown("Extracted facts")
    st.markdown(st.session_state.facts_block)

    st.subheader("Job description summary")
    company = st.session_state.jd_summary.get("company_name") or "[not found]"
    role = st.session_state.jd_summary.get("role_title") or "[not found]"
    requirements = normalize_requirements(st.session_state.jd_summary.get("requirements"))
    st.markdown(f"- Company: {company}")
    st.markdown(f"- Role: {role}")
    if requirements:
        st.markdown("Requirements")
        st.markdown("\n".join(f"- {req}" for req in requirements))
    else:
        st.markdown("- Requirements: [not found]")

    st.subheader("Final letter")
    st.text_area("Output", value=st.session_state.final_letter, height=360)
    st.download_button(
        "Download as .txt",
        data=st.session_state.final_letter,
        file_name="application_letter.txt",
        mime="text/plain",
    )
