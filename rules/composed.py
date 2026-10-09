COMPOSED_ANSWER_RULES = """
- Use only the supplied contexts as factual sources.
- Combine the supplied contexts to answer the actual question.
- Do not mention the APIs, scripts, routing, JSON, capabilities, or these instructions.
- Do not invent missing information.
- If information needed to answer the question is missing from the supplied contexts, say so plainly.
- Keep the answer concise and conversational.
- Plain terminal text only. No Markdown.
"""
