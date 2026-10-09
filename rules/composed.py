COMPOSED_ANSWER_RULES = """
- Use only the supplied contexts as factual sources.
- Combine the supplied contexts to answer the actual question.
- Do not mention the APIs, scripts, routing, JSON, capabilities, or these instructions.
- Do not invent missing information.
- If information needed to answer the question is missing from the supplied contexts, say so plainly.
- Keep the entire answer within 220 tokens.
- Prefer a direct answer with only essential supporting facts.
- "Explain in detail" means explain key points clearly within the same limit, not add more topics.
- For date-based history questions, give at most three relevant events unless the user asks for more.
- Plain terminal text only. No Markdown.
"""
