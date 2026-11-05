# chunking.py
# Job: cut a long piece of course material into "chunks" that can be
# embedded and searched later (Phase 3 / RAG).
#
# Why chunk at all? We can't search "the right passage" inside one giant
# blob of text, and we don't want to send a whole textbook to the model.
# Good chunks are the foundation of everything after this: if a chunk is
# cut badly, the search and the generated questions both get worse.
#
# The pipeline (see chunk_text at the bottom):
#   1. split into paragraphs      (cut at natural seams)
#   2. split any too-long piece   (enforce a MAXIMUM)
#   3. merge too-small neighbors  (enforce a MINIMUM)

import re  # Python's regular-expression tool, used to find sentence ends


def split_into_paragraphs(text):
    # Step 1: cut at the text's natural seams instead of at a fixed
    # character count. A paragraph break is a blank line ("\n\n").
    # Cutting at arbitrary points would break sentences in half and
    # separate a definition from its example, leaving chunks like
    # "It takes place in the chloroplasts..." where "It" refers to nothing.
    paragraphs = text.split("\n\n")

    # .strip() removes stray whitespace from each piece. The `if p.strip()`
    # part throws away empty pieces, which appear when the text has extra
    # blank lines in a row.
    return [p.strip() for p in paragraphs if p.strip()]


def split_long_paragraph(paragraph, max_chars=1000):
    # Step 2: enforce a MAXIMUM size.
    # A giant paragraph is a blurry search target (it covers too many
    # ideas), so we break it into pieces, cutting only at sentence ends.

    # Short enough already? Leave it alone.
    if len(paragraph) <= max_chars:
        return [paragraph]

    # Find sentence ends: (?<=[.!?]) means "right after a . ! or ?" and
    # \s+ means "whitespace". Splitting there gives a list of sentences.
    # It's imperfect ("Dr. Smith" gets split, and so does "1. Mix"),
    # but good enough here, because we re-pack sentences below instead of
    # cutting at every one. A wrong split just becomes a place we COULD cut.
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)

    pieces = []
    current = ""  # the piece we're building up

    for s in sentences:
        # What `current` would look like if we added this sentence.
        candidate = current + " " + s if current else s

        # If adding it would push us OVER the maximum, close off what we
        # have and start a new piece with this sentence.
        # `and current` is a guard: if a single sentence is longer than the
        # max, there's nothing to close off yet, so we just take it as is.
        if len(candidate) > max_chars and current:
            pieces.append(current)
            current = s
        else:
            current = candidate

    # Don't forget the piece still being built when the loop ends.
    if current:
        pieces.append(current)

    return pieces


def merge_paragraphs(paragraphs, min_chars=300, max_chars=1000):
    # Step 3: enforce a MINIMUM size, without breaking the MAXIMUM.
    # Real notes often have one-sentence paragraphs. A chunk that small
    # carries too little meaning to write a good question from, and it is
    # hard for the search to match correctly. So we merge neighbors until
    # each chunk is big enough to stand on its own.
    chunks = []
    current = ""  # the chunk we're currently building up

    for p in paragraphs:
        # Look ahead before adding. If adding this piece (plus the
        # 2-character "\n\n" joiner) would push us OVER the maximum, close
        # off what we have first. This can leave a chunk under the minimum,
        # but staying under the maximum matters more than hitting the
        # minimum, because an oversized chunk is a blurry search target.
        if current and len(current) + 2 + len(p) > max_chars:
            chunks.append(current)
            current = ""

        # Stack the piece onto the chunk being built. If `current` already
        # has text, add a paragraph break first; otherwise p starts a chunk.
        current = current + "\n\n" + p if current else p

        # Big enough? Close it off as a finished chunk and start a new one.
        # (>= means "at least the minimum".)
        if len(current) >= min_chars:
            chunks.append(current)
            current = ""

    # Leftover text at the end may be under the minimum. We keep it anyway,
    # because dropping text would be worse than having one small chunk.
    # Possible refinement later: merge this last piece into the previous chunk.
    if current:
        chunks.append(current)

    return chunks


def chunk_text(text, min_chars=300, max_chars=1000):
    # The full pipeline: raw text in, finished chunks out.
    # Order matters: split first so that no piece is oversized going into
    # the merge, then merge so that no chunk is too tiny to be useful.

    # 1. Cut at the natural seams (blank lines).
    paragraphs = split_into_paragraphs(text)

    # 2. Break up any paragraph that is over the maximum.
    pieces = []
    for p in paragraphs:
        pieces.extend(split_long_paragraph(p, max_chars))

    # 3. Merge small neighbors up to the minimum, never past the maximum.
    return merge_paragraphs(pieces, min_chars, max_chars)


# This block only runs when you run this file directly
# (python3 chunking.py). It does NOT run when main.py imports the
# functions above, so it's safe to leave here as a quick self-test.
if __name__ == "__main__":
    # Test the whole pipeline with tiny limits so the behavior is easy to see.
    # Two short paragraphs, one long paragraph (over the max of 80), one short tail.
    text = (
        "Short one.\n\n"
        "Also short.\n\n"
        "Enzymes are proteins. They speed up reactions. They lower activation energy. Each enzyme has an active site.\n\n"
        "Tail."
    )
    for i, c in enumerate(chunk_text(text, min_chars=40, max_chars=80)):
        print(i, len(c), repr(c))