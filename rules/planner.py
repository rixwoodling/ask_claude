PLANNER_RULES = """
- Include every capability needed to answer the question accurately.
- Use only capabilities listed in the available capability registry.
- Use general when no registered capability is required.
- Do not include capabilities that are merely related. Include only capabilities whose data is required.
- If a later capability needs a value produced by an earlier capability, express that dependency with an explicit JSON-path reference.
- Dependency references must use the exact form:
  $<capability>.<field>
  or
  $<capability>.<list_field>[<index>]
- Example:
  $sports.games[0].venue
- A dependency reference must point to a field that the referenced capability actually returns.
- Never invent placeholder values for dependencies.
- Never use placeholder strings such as:
  "venue_location_from_sports_lookup"
  "date_from_sports"
  "location_from_previous_lookup"
  or similar text.
- If a required value is available from a previous capability result, reference that result with $ syntax rather than inventing or paraphrasing the value.
- Do not encode fixed relationships between capabilities.
- Determine dependencies from the user's question and the data available from previously selected capabilities.
- Return strictly valid JSON.
- Numeric values must use standard JSON number syntax.
- Do not use leading zeros in numbers.
- For example, use 100, not 0100 or 00.
- Do not add explanatory text before or after the JSON object.
- If the question can be answered from general knowledge without data from a registered capability, return an empty capabilities list.
- Do not ask the user to clarify a general-knowledge question.
- Do not answer the user's question in the planner response.
- If no registered capability is required, the plan must contain no lookups.
"""
