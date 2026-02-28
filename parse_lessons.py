#!/usr/bin/env python3
"""
parse_lessons.py - Parse the Easy Croatian extracted_text.txt into lessons.json

No external dependencies beyond the Python standard library.
"""

import re
import json
import os

INPUT_FILE = os.path.join(os.path.dirname(__file__), "extracted_text.txt")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "lessons.json")

# ── Regex patterns ───────────────────────────────────────────────────────────
# Footer pattern: "Easy Croa!an (rev. 47b) / section name"
FOOTER_SECTION_RE = re.compile(r"^Easy Croa[!t]an \(rev\. 47b\) / .+$")
# Page counter line: "9 / 600"
PAGE_LINE_RE = re.compile(r"^(\d+) / 600$")

# Section ID patterns used in both TOC and content
LESSON_ID_RE = re.compile(r"^(\d{2}) (.+)$")
APPENDIX_ID_RE = re.compile(r"^(A\d) (.+)$")
LIST_ID_RE = re.compile(r"^(L\d) (.+)$")
CORE_DICT_RE = re.compile(r"^Core Dictionary$")

# ── Content patterns ─────────────────────────────────────────────────────────
EXERCISE_RE = re.compile(r"^• Exercise$")
SPI_RE = re.compile(r"^• Something Possibly Interesting$")
SEPARATOR_RE = re.compile(r"^_{4,}$")
TIP_RE = re.compile(r"^(Warning\.|A (warning|suggestion|note)\.|Note\.|Tip\.)", re.IGNORECASE)

REGIONAL_MARKER = "®"
VERB_KEYWORDS = {"impf.", "perf.", "v.p.", "v.t.", "inf", "pres"}
ADJ_KEYWORDS = {"adj.", "adv.", "pass. adj.", "rel. adj."}

# ── Croatian language helpers ────────────────────────────────────────────────
CROATIAN_DIACRITICS = frozenset("čćđšžČĆĐŠŽ")
# Croatian infinitive endings
CROATIAN_INF_RE = re.compile(
    r"[a-zčćđšžA-ZČĆĐŠŽ]+(ati|iti|eti|ovati|ivati|nuti|sti|ći)$",
    re.IGNORECASE,
)


def has_diacritic(s):
    return any(c in CROATIAN_DIACRITICS for c in s)


def looks_croatian(word):
    """Return True if a word looks like it is Croatian."""
    return has_diacritic(word) or bool(CROATIAN_INF_RE.match(word))


# ── Vocabulary detection ─────────────────────────────────────────────────────
# A vocab line: Croatian_word(s) [optional (form)] English_translation [®]
# Constraints: no sentence-ending period, Croatian first word, English follows.
VOCAB_FULL_RE = re.compile(
    r"^([a-zA-ZčćđšžČĆĐŠŽ][a-zA-ZčćđšžČĆĐŠŽ\-/ ]{0,50}?(?:\([^)]+\))?)\s+"
    r"([a-z®][^.!?]*|[A-Z][a-z ,;:\-®()/]{1,100})$"
)

# ── Example sentence detection ───────────────────────────────────────────────
# Two sentences on one line: "Croatian sentence.  English sentence."
EXAMPLE_LINE_RE = re.compile(
    r"^([^.!?]+[.!?])\s+([A-Z(][^.!?]+[.!?]\s*®?)$"
)


# ── TOC parsing ──────────────────────────────────────────────────────────────

def parse_toc(lines):
    """
    Parse the Table of Contents from the raw lines.
    Returns dict: {section_id: {"title": str, "page": int}}
    The TOC appears between "Contents" and the second occurrence of
    "Introduction" (the one followed by actual prose, not a page number).
    """
    toc = {}

    # Find the "Contents" line
    contents_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "Contents":
            contents_idx = i
            break

    if contents_idx is None:
        return toc

    # Find the "Introduction" that starts actual prose:
    # it is followed by a long non-numeric line (not just a page number).
    intro_idx = None
    for i in range(contents_idx + 1, min(contents_idx + 400, len(lines))):
        if lines[i].strip() == "Introduction":
            # Check if the next non-blank line is prose (not a page number)
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and not lines[j].strip().isdigit():
                intro_idx = i
                break

    end = intro_idx if intro_idx else min(contents_idx + 350, len(lines))
    toc_lines = lines[contents_idx:end]

    i = 0
    while i < len(toc_lines):
        line = toc_lines[i].strip()

        sec_id = None
        sec_title = None

        for pat in (LESSON_ID_RE, APPENDIX_ID_RE, LIST_ID_RE):
            m = pat.match(line)
            if m:
                sec_id = m.group(1)
                sec_title = m.group(2).strip()  # strip trailing whitespace
                break

        if sec_id is None and CORE_DICT_RE.match(line):
            sec_id = "CORE"
            sec_title = "Core Dictionary"

        if sec_id is not None:
            # Next non-empty line is the page number
            page = None
            j = i + 1
            while j < len(toc_lines):
                next_line = toc_lines[j].strip()
                if next_line.isdigit():
                    page = int(next_line)
                    break
                elif next_line:
                    break
                j += 1
            toc[sec_id] = {"title": sec_title, "page": page}

        i += 1

    return toc


# ── Footer stripping ─────────────────────────────────────────────────────────

def strip_footers(lines):
    """Remove footer lines: the 'Easy Croa!an...' line and the 'N / 600' line after it."""
    clean = []
    i = 0
    while i < len(lines):
        if FOOTER_SECTION_RE.match(lines[i].strip()):
            i += 1
            # Skip blank lines
            while i < len(lines) and lines[i].strip() == "":
                i += 1
            # Skip page counter line
            if i < len(lines) and PAGE_LINE_RE.match(lines[i].strip()):
                i += 1
            continue
        clean.append(lines[i])
        i += 1
    return clean


# ── Section splitting ────────────────────────────────────────────────────────

def normalise_title(title):
    """Lowercase, collapse spaces, strip trailing punctuation and parenthetical for comparison."""
    # Remove parenthetical suffixes like "(u/c)" that may differ between TOC and content
    t = re.sub(r"\s*\([^)]+\)\s*$", "", title)
    return re.sub(r"\s+", " ", t.strip().lower()).rstrip(".,:;")


def split_into_sections(raw_lines, toc):
    """
    Split raw lines into named sections using the TOC as the authority.
    Returns list of dicts: {id, title, page_start, lines}
    """
    # Build a lookup: normalised_title -> (id, title, page)
    toc_by_norm = {}
    for sec_id, info in toc.items():
        norm = normalise_title(info["title"])
        toc_by_norm[norm] = (sec_id, info["title"], info.get("page"))

    # Also build lookup by id
    toc_by_id = {sec_id: info for sec_id, info in toc.items()}

    def is_known_header(stripped_line, prev_lines):
        """
        Return (id, title, page) if this line is a known section header,
        else None.

        Additional context check: real headers are preceded by a footer
        (Easy Croa!an...) or a blank line, NOT by prose ending with a colon.
        """
        # Quick context check: if the previous non-blank line ends with a colon
        # it's a cross-reference like "for more details, check: 50 Because..."
        for prev in reversed(prev_lines[-5:]):
            p = prev.strip()
            if p:
                if p.endswith(":") or p.endswith(","):
                    return None
                break
        # Try to match pattern and look up in TOC
        for pat in (LESSON_ID_RE, APPENDIX_ID_RE, LIST_ID_RE):
            m = pat.match(stripped_line)
            if m:
                sid = m.group(1)
                candidate_title = m.group(2).strip().rstrip()
                # Check if this id+title combination matches a TOC entry
                if sid in toc_by_id:
                    toc_title = toc_by_id[sid]["title"]
                    norm_cand = normalise_title(candidate_title)
                    norm_toc = normalise_title(toc_title)
                    # Exact match OR: the TOC title starts with the candidate
                    # (handles truncated titles from PDF line-wrapping).
                    # Require at least 15 chars for the prefix check to avoid
                    # false positives on short strings.
                    if (norm_cand == norm_toc or
                            (len(norm_cand) >= 15 and norm_toc.startswith(norm_cand))):
                        return (sid, toc_by_id[sid]["title"], toc_by_id[sid].get("page"))
        if CORE_DICT_RE.match(stripped_line) and "CORE" in toc_by_id:
            return ("CORE", "Core Dictionary", toc_by_id["CORE"].get("page"))
        return None

    sections = []
    current = None

    # Find the real start of content (after TOC), past the second "Introduction"
    content_start = 0
    intro_count = 0
    for i, line in enumerate(raw_lines):
        if line.strip() == "Introduction":
            intro_count += 1
            if intro_count == 2:
                content_start = i
                break

    # Process only from content start onward
    for i in range(content_start, len(raw_lines)):
        line = raw_lines[i]
        stripped = line.strip()

        header = is_known_header(stripped, raw_lines[max(0, i-5):i])
        if header:
            if current is not None:
                sections.append(current)
            sec_id, sec_title, page = header
            current = {
                "id": sec_id,
                "title": sec_title,
                "page_start": page,
                "lines": [],
            }
            continue

        if current is not None:
            current["lines"].append(line.rstrip("\n"))

    if current is not None:
        sections.append(current)

    return sections


# ── Content parsing helpers ──────────────────────────────────────────────────

def detect_vocab_type(notes_str, english_str):
    """Guess part-of-speech from content."""
    combined = (notes_str + " " + english_str).lower()
    if any(kw in combined for kw in VERB_KEYWORDS):
        return "verb"
    if re.search(r"\b(m|f|n)\b", combined):
        return "noun"
    for kw in ADJ_KEYWORDS:
        if kw in combined:
            return "adjective"
    return ""


def parse_vocab_line(line):
    """
    Parse a vocabulary line like 'čitati read' or 'ležati (leži) lie down ®'.
    Returns dict or None.

    A vocab line:
    - Is short (< 120 chars)
    - Does NOT end with a sentence-terminating period in its English part
      (so it's not an example sentence pair)
    - The FIRST word looks Croatian (has diacritic or verb ending)
    """
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return None

    # Lines that are clearly sentences or prose
    if stripped.endswith(":") or stripped.startswith("(") and ")" not in stripped:
        return None

    # Parse with the vocabulary regex
    m = VOCAB_FULL_RE.match(stripped)
    if not m:
        return None

    croatian_raw = m.group(1).strip()
    english_raw = m.group(2).strip()

    # The first word of the Croatian part must look Croatian
    first_word = croatian_raw.split()[0].rstrip("()")
    if not looks_croatian(first_word):
        return None

    # Reject if English part looks like a continuation of a sentence
    # (starts with common English articles/pronouns in a sentence context)
    if re.match(r"^(The|In|It|At|On|For|This|That|These|Those|There|Here)\s+[a-z]", english_raw):
        return None

    # Extract parenthetical note from Croatian (e.g. "(leži)")
    paren_m = re.search(r"\(([^)]+)\)", croatian_raw)
    paren_note = ""
    if paren_m:
        paren_note = paren_m.group(0)
        croatian_raw = croatian_raw[:paren_m.start()].strip()

    # Extract ® from English
    regional = ""
    if REGIONAL_MARKER in english_raw:
        regional = "®"
        english_raw = english_raw.replace(REGIONAL_MARKER, "").strip()

    notes_parts = [p for p in [paren_note, regional] if p]
    notes = " ".join(notes_parts)

    word_type = ""
    if paren_note or bool(CROATIAN_INF_RE.match(croatian_raw.split()[0])):
        word_type = "verb"

    return {
        "croatian": croatian_raw,
        "english": english_raw.rstrip(".,"),
        "notes": notes,
        "type": word_type,
    }


def parse_example_line(line):
    """
    Parse a paired sentence line: 'Ana čita.  Ana is reading.'
    Returns dict or None.

    Heuristics:
    - Line ends with a sentence-ending punctuation (possibly + ®)
    - There are two distinct sentence-like parts on the line
    - The line is not too long (< 250 chars)
    - The first part contains a Croatian word or name
    """
    stripped = line.strip()
    if not stripped or len(stripped) > 250:
        return None

    # Must end with sentence punctuation (optionally followed by ®)
    if not re.search(r"[.!?]\s*®?$", stripped):
        return None

    m = EXAMPLE_LINE_RE.match(stripped)
    if not m:
        return None

    croatian = m.group(1).strip()
    english = m.group(2).strip()

    # The Croatian part should be at least 5 characters (not just a letter + period)
    if len(croatian.rstrip(".!?")) < 5:
        return None

    # Both parts should be short (a sentence, not a whole paragraph)
    if len(croatian) > 150 or len(english) > 150:
        return None

    # Require at least a Croatian word or a person name in the first part
    if not (has_diacritic(croatian) or re.search(r"\b[A-Z][a-z]+\b", croatian)):
        return None

    # Reject if the first part is clearly English prose (starts with common English words)
    if re.match(r"^(the|in|it|at|on|for|this|that|from|with|to|as|by|of|"
                r"a |an |so |but|and|or |not|no |also|such|some|most|"
                r"The|In|It|At|On|For|This|That|From|With|To|As|By|Of|"
                r"A |An |So |But|And|Or |Not|No |Also|Such|Some|Most)\s",
                croatian):
        return None

    return {"croatian": croatian, "english": english}


def parse_exercise_block(lines, start):
    """
    Parse an exercise block starting at 'start' (the '• Exercise' line).
    Returns (exercise_dict, next_line_index).
    """
    exercise = {"instruction": "", "items": []}
    i = start + 1
    instruction_parts = []
    items = []

    while i < len(lines):
        stripped = lines[i].strip()
        if EXERCISE_RE.match(stripped) or SPI_RE.match(stripped) or SEPARATOR_RE.match(stripped):
            break
        if stripped.startswith("Check answers"):
            i += 1
            break
        # Detect fill-in-the-blank items (lines with 4+ underscores)
        if re.search(r"_{4,}", stripped) and len(stripped) > 4:
            items.append({"prompt": stripped, "answer": ""})
        elif not items:
            # Still in instruction
            if stripped:
                instruction_parts.append(stripped)
        i += 1

    exercise["instruction"] = " ".join(instruction_parts).strip()
    exercise["items"] = items
    return exercise, i


def generate_topics(title, content_text):
    """Auto-generate topic tags from title and key content terms."""
    topics = []
    combined = (title + " " + content_text).lower()

    keyword_map = [
        (r"alphabet", "alphabet"),
        (r"pronunciation", "pronunciation"),
        (r"vowel", "vowels"),
        (r"consonant", "consonants"),
        (r"stress", "stress"),
        (r"\bverb", "verbs"),
        (r"\bnoun", "nouns"),
        (r"\badjective", "adjectives"),
        (r"\bpronoun", "pronouns"),
        (r"\badverb", "adverbs"),
        (r"\bpreposition", "prepositions"),
        (r"accusative", "accusative"),
        (r"genitive", "genitive"),
        (r"\bdative\b", "dative"),
        (r"\blocative\b", "locative"),
        (r"instrumental", "instrumental"),
        (r"vocative", "vocative"),
        (r"\bplural\b", "plural"),
        (r"past tense", "past-tense"),
        (r"future tense", "future-tense"),
        (r"present tense", "present-tense"),
        (r"\bnumber", "numbers"),
        (r"\bgender\b", "gender"),
        (r"color|colour", "colors"),
        (r"question", "questions"),
        (r"negation|negative", "negation"),
        (r"conditional", "conditionals"),
        (r"relative clause", "relative-clauses"),
        (r"dialect", "dialects"),
        (r"comparative", "comparatives"),
    ]
    seen = set()
    for pattern, tag in keyword_map:
        if re.search(pattern, combined) and tag not in seen:
            topics.append(tag)
            seen.add(tag)

    return topics[:10]


def parse_core_dict_entries(lines):
    """Parse Core Dictionary section into structured word entries."""
    entries = []

    # Find the alphabet index block (a sequence of single-letter capital lines
    # like A, B, C, Č, Ć, D, DŽ, Đ, ..., Ž) which marks end of preamble.
    alphabet_end = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^[A-ZČĆĐŠŽ]{1,2}$", stripped):
            # Check if we're in the middle of the alphabet index block
            # (look ahead for more single-capital lines)
            ahead = sum(
                1 for l in lines[i:i+10]
                if re.match(r"^[A-ZČĆĐŠŽ]{1,2}$", l.strip())
            )
            if ahead >= 5:
                # Found the alphabet index; the end is the last single-letter line
                j = i
                while j < len(lines) and re.match(r"^[A-ZČĆĐŠŽ]{1,2}$", lines[j].strip()):
                    j += 1
                alphabet_end = j
                break

    # Parse entries only after the alphabet index block
    # Pattern for a dictionary entry:
    #   word_form  type  meaning
    # where type is one of the known POS abbreviations
    entry_re = re.compile(
        r"^([a-zA-ZčćđšžČĆĐŠŽ][a-zA-ZčćđšžČĆĐŠŽ\-\(\)\s/\.ª~]{0,60}?)"
        r"\s+(m|mª|f|n|adj\.|adv\.|impf\.|perf\.|v\.p\.|v\.t\.|"
        r"pass\. adj\.|rel\. adj\.|conj\.|prep\.|pron\.|num\.)"
        r"\s+(.+)$"
    )

    for line in lines[alphabet_end:]:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip derived-word lines (start with ·) and note lines (start with —)
        if stripped.startswith("·") or stripped.startswith("—"):
            continue
        # Skip single-letter section separators (A, B, C, ...)
        if re.match(r"^[A-ZČĆĐŠŽ]{1,2}$", stripped):
            continue
        m = entry_re.match(stripped)
        if m:
            word = m.group(1).strip()
            pos = m.group(2).strip()
            meaning = m.group(3).strip()
            # The Croatian word part should be reasonably short (1-3 words)
            word_word_count = len(word.split())
            if word_word_count > 4:
                continue
            # Clean up the meaning: remove § references and trailing punctuation
            meaning_clean = re.sub(r"§\s*\d+(?:,\s*\d+)*", "", meaning).strip()
            meaning_clean = re.sub(r"\{[^}]+\}", "", meaning_clean).strip()
            meaning_clean = meaning_clean.rstrip(".,;")
            entries.append({
                "croatian": word,
                "english": meaning_clean,
                "part_of_speech": pos,
            })
    return entries


# ── Section content parser ───────────────────────────────────────────────────

def parse_section_content(sec):
    """
    Parse a lesson/appendix section lines into structured JSON fields.
    """
    lines = strip_footers(sec["lines"])

    content_sections = []
    vocabulary = []
    example_sentences = []
    tables = []
    tips = []
    grammar_notes = []
    exercises = []
    regional_notes = []

    i = 0
    n = len(lines)
    text_buffer = []
    in_regional = False
    regional_buffer = []

    def flush_text():
        nonlocal text_buffer
        text = "\n".join(text_buffer).strip()
        if text:
            content_sections.append({"type": "explanation", "text": text})
        text_buffer = []

    def flush_regional():
        nonlocal regional_buffer, in_regional
        text = "\n".join(regional_buffer).strip()
        if text:
            regional_notes.append(text)
        regional_buffer = []
        in_regional = False

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Exercise block
        if EXERCISE_RE.match(stripped):
            flush_text()
            if in_regional:
                flush_regional()
            ex, i = parse_exercise_block(lines, i)
            exercises.append(ex)
            continue

        # "Something Possibly Interesting" block
        if SPI_RE.match(stripped):
            flush_text()
            if in_regional:
                flush_regional()
            spi_lines = []
            i += 1
            while i < n:
                s = lines[i].strip()
                if EXERCISE_RE.match(s) or SEPARATOR_RE.match(s) or SPI_RE.match(s):
                    break
                spi_lines.append(lines[i].rstrip())
                i += 1
            text = "\n".join(spi_lines).strip()
            if text:
                content_sections.append({"type": "spi", "text": text})
            continue

        # Regional separator
        if SEPARATOR_RE.match(stripped):
            flush_text()
            if in_regional:
                flush_regional()
            in_regional = True
            i += 1
            continue

        # Tip / warning
        if TIP_RE.match(stripped):
            flush_text()
            if in_regional:
                flush_regional()
            tip_parts = [stripped]
            i += 1
            # Collect continuation lines (non-blank until next blank or separator)
            while i < n:
                s = lines[i].strip()
                if not s or SEPARATOR_RE.match(s) or EXERCISE_RE.match(s):
                    break
                tip_parts.append(s)
                i += 1
            tips.append(" ".join(tip_parts))
            continue

        # Regional content
        if in_regional:
            regional_buffer.append(stripped)
            i += 1
            continue

        # Example sentence detection
        ex_line = parse_example_line(line)
        if ex_line:
            flush_text()
            example_sentences.append(ex_line)
            i += 1
            continue

        # Vocabulary line detection
        vocab_item = parse_vocab_line(line)
        if vocab_item:
            flush_text()
            vocabulary.append(vocab_item)
            i += 1
            continue

        # Grammar note detection (lines that mention grammatical terms)
        if re.search(
            r"\b(accusative|genitive|dative|locative|instrumental|nominative|vocative"
            r"|infinitive|present tense|past tense|future tense)\b",
            stripped, re.IGNORECASE
        ):
            grammar_notes.append(stripped)

        # Regular text (goes into explanation)
        text_buffer.append(line.rstrip())
        i += 1

    flush_text()
    if in_regional:
        flush_regional()

    all_text = " ".join(cs["text"] for cs in content_sections)
    topics = generate_topics(sec["title"], all_text)

    return {
        "topics": topics,
        "content_sections": content_sections,
        "vocabulary": vocabulary,
        "example_sentences": example_sentences,
        "tables": tables,
        "tips": tips,
        "grammar_notes": grammar_notes,
        "exercises": exercises,
        "regional_notes": regional_notes,
    }


# ── Main builder ─────────────────────────────────────────────────────────────

def build_output(sections, toc):
    """Assemble the final JSON structure."""
    lessons = []
    appendices = []
    lists = []
    core_dictionary = []

    for sec in sections:
        sid = sec["id"]

        if sid == "CORE":
            core_dictionary = parse_core_dict_entries(strip_footers(sec["lines"]))
            continue

        if re.match(r"^A\d$", sid):
            content = parse_section_content(sec)
            appendices.append({
                "id": sid,
                "title": sec["title"],
                "page_start": sec.get("page_start"),
                "content": "\n\n".join(
                    cs["text"] for cs in content["content_sections"]
                ),
                "vocabulary": content["vocabulary"],
                "grammar_notes": content["grammar_notes"],
            })
            continue

        if re.match(r"^L\d$", sid):
            content = parse_section_content(sec)
            lists.append({
                "id": sid,
                "title": sec["title"],
                "page_start": sec.get("page_start"),
                "content": "\n\n".join(
                    cs["text"] for cs in content["content_sections"]
                ),
                "vocabulary": content["vocabulary"],
            })
            continue

        # Numbered lesson
        content = parse_section_content(sec)
        lessons.append({
            "id": sid,
            "title": sec["title"],
            "page_start": sec.get("page_start"),
            "topics": content["topics"],
            "content_sections": content["content_sections"],
            "vocabulary": content["vocabulary"],
            "example_sentences": content["example_sentences"],
            "tables": content["tables"],
            "tips": content["tips"],
            "grammar_notes": content["grammar_notes"],
            "exercises": content["exercises"],
            "regional_notes": content["regional_notes"],
        })

    # Sort lessons numerically by their two-digit ID
    lessons.sort(key=lambda x: int(x["id"]))

    return {
        "metadata": {
            "title": "Easy Croatian",
            "author": "Daniel N.",
            "revision": "47b",
            "year_range": "2009-2019",
            "source": "easy-croatian.com",
        },
        "lessons": lessons,
        "appendices": appendices,
        "lists": lists,
        "core_dictionary": core_dictionary,
    }


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_lines = [line.rstrip("\n") for line in f]

    print(f"Read {len(raw_lines)} lines from {INPUT_FILE}")

    toc = parse_toc(raw_lines)
    print(f"TOC entries found: {len(toc)}")
    for sid, info in sorted(toc.items()):
        print(f"  [{sid}] {info['title']} (page {info.get('page')})")

    sections = split_into_sections(raw_lines, toc)
    print(f"\nContent sections found: {len(sections)}")
    for sec in sections:
        print(f"  [{sec['id']}] {sec['title']} ({len(sec['lines'])} lines)")

    output = build_output(sections, toc)

    n_lessons = len(output["lessons"])
    n_appendices = len(output["appendices"])
    n_lists = len(output["lists"])
    n_dict = len(output["core_dictionary"])
    print(
        f"\nOutput: {n_lessons} lessons, {n_appendices} appendices, "
        f"{n_lists} lists, {n_dict} dictionary entries"
    )

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(OUTPUT_FILE) // 1024
    print(f"Written to {OUTPUT_FILE} ({size_kb} KB)")


if __name__ == "__main__":
    main()
