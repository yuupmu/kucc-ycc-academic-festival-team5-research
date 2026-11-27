def clean_title(text: str) -> str:
    # [P1] Input validation not needed per spec, proceed directly
    # [P2] Remove trailing whitespace and convert to lowercase
    text = text.rstrip().lower()  # [P2] Remove trailing whitespace and convert to lowercase

    # [H3] If result is empty after stripping, return 'untitled'
    if not text:
        return "untitled"

    # [H1] Replace multiple consecutive spaces with a single space
    # [H2] Hyphens are kept as-is (count and position preserved)
    # Logic: Only whitespace characters are collapsed; hyphens are not part of the whitespace group
    # Regex r'\s+' matches one or more ASCII whitespace characters (spaces, tabs, newlines)
    # It does NOT match hyphens, so sequences like "a  -  b" become "a - b"
    import re
    text = re.sub(r'\s+', ' ', text)

    return text

import re