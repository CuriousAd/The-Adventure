def build_root_generation_prompt(theme: str, target_depth: int, branching_factor: int) -> str:
    return f"""
You are building the opening of a choose-your-own-adventure story.

Theme: {theme}
Maximum story depth: {target_depth}
Choices per non-ending node: exactly {branching_factor}

Generate only:
1. the story title
2. the root node
3. the root node's immediate option texts

Rules:
- Do not generate nested next nodes.
- Do not generate markdown, code fences, or commentary.
- The root node must not be an ending.
- The root node must have exactly {branching_factor} options.
- Every options field must be a real JSON array, never a string.
- Make the story fun, engaging, and faithful to the theme.
- Use simple, quirky wording that feels playful without being childish.
- Keep the scene short and punchy for a game UI.
- Make each choice clear, tempting, and a little flavorful.
""".strip()


def build_initial_bundle_generation_prompt(theme: str, target_depth: int, branching_factor: int) -> str:
    return f"""
You are building the playable opening of a choose-your-own-adventure story.

Theme: {theme}
Maximum story depth: {target_depth}
Choices per non-ending node: exactly {branching_factor}

Generate only:
1. the story title
2. the root node with exactly {branching_factor} option texts
3. exactly {branching_factor} child nodes, one for each root option
4. each child node's immediate next option texts

Rules:
- This is a shallow startup bundle, not a full story tree.
- Do not generate grandchildren or nested next nodes beyond the listed child nodes.
- childNodes must use zero-based optionIndex values matching the root option order.
- The root node must not be an ending.
- Child nodes are depth 2 and must not be endings.
- Every non-ending options field must be a real JSON array, never a string.
- Do not generate markdown, code fences, or commentary.
- Make the story fun, engaging, and faithful to the theme.
- Use simple, quirky wording that feels playful without being childish.
- Keep each scene short and punchy for a game UI.
- Make each choice clear, tempting, and a little flavorful.
""".strip()


def build_branch_generation_prompt(
    theme: str,
    path_context: str,
    option_text: str,
    depth: int,
    target_depth: int,
    branching_factor: int
) -> str:
    must_end = depth >= target_depth
    may_end = depth >= 4

    if must_end:
        ending_instruction = "This node must be an ending. Set options to null."
    elif may_end:
        ending_instruction = (
            f"This node may be an ending if it feels satisfying. If it is not an ending, "
            f"it must have exactly {branching_factor} options."
        )
    else:
        ending_instruction = f"This node must not be an ending and must have exactly {branching_factor} options."

    return f"""
You are expanding one branch of a choose-your-own-adventure story.

Theme: {theme}
Current depth: {depth}
Target total depth: {target_depth}
Chosen option leading here: {option_text}

Story path so far:
{path_context}

Generate only the current node reached after the chosen option.

Rules:
- {ending_instruction}
- If this is an ending, mark whether it is a winning ending or not.
- If this is not an ending, options must contain only the immediate next choice texts.
- Do not generate nested next nodes.
- Every options field must be a real JSON array or real null, never a string.
- Do not generate markdown, code fences, or commentary.
- Keep the node coherent with the earlier path.
- Make the story fun, engaging, and faithful to the theme.
- Use simple, quirky wording that feels playful without being childish.
- Keep the scene short and punchy for a game UI.
- Make each choice clear, tempting, and a little flavorful.
""".strip()


def build_json_repair_prompt(label: str, raw_text: str, original_prompt: str) -> str:
    return f"""
Repair the malformed JSON for this {label}.

Original generation instructions:
{original_prompt}

Malformed JSON:
{raw_text}

Return only corrected JSON that matches the requested schema.
Do not add commentary, markdown, or code fences.
Convert stringified arrays/objects/null values into real JSON values.
""".strip()
