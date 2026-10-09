INTENT_RULES = """
Classify the user's conversational intent.

Return exactly one word:
serious
playful
ambiguous

Use serious when the user appears to genuinely want factual,
technical, practical, or explanatory information.

Use playful when the question is clearly absurd, humorous,
anthropomorphic, exaggerated, whimsical, or phrased like a joke.

Use ambiguous when either a serious or playful interpretation
is reasonably plausible.

Do not answer the user's question.
Return only the classification word.
"""
