
"""CP-002 R-02 / N-06 test data: hand-written benign requests and pasted-text samples.

PROVENANCE: every item below was written by hand by Claude for this change (nothing is scraped, nothing
comes from real users). They are representative, not statistical: they show which kinds of ordinary text
the matching views leave alone and which new-match classes they open. A real-traffic corpus would be the
better evidence and is tracked as a limitation of CP-002 (the owner can append items here).
Non-ASCII characters are written as escapes so editors cannot alter them.
"""

# ---- R-02: benign requests (>= 60). Most must be CLEAN with no rule; the few that open a new-match class
# are expected to appear in matching_view_new_matches.json with a written justification (N-01).
BENIGN = [
    "What is the capital of Australia?",
    "Can you explain how photosynthesis works to a ten year old?",
    "Write a haiku about autumn rain.",
    "Summarise the plot of Pride and Prejudice in three sentences.",
    "How do I convert a list of strings to integers in Python?",
    "What's the difference between a virus and a bacterium?",
    "I don't understand why my sourdough starter isn't rising. Any ideas?",
    "Translate 'good morning' into French, Spanish and German.",
    "It's my daughter's birthday on Friday; suggest five cake flavours.",
    "Rewrite this sentence to sound more formal: gonna be late, sorry.",
    "Explain the state-of-the-art in speech recognition in plain language.",
    "Give me a well-known example of a pre-existing condition clause in insurance, in general terms.",
    "Draft a thank-you note to my neighbour for watering my plants.",
    "How long should I boil an egg for a runny yolk?",
    "What does 'e-mail etiquette' usually cover in a company handbook?",
    "Suggest a 3-day itinerary for Lisbon \u2014 we like food and history.",
    "Compare the pros and cons of electric vs hybrid cars.",
    "Why is the sky blue during the day but red at sunset?",
    "Can you proofread: 'Their going to the park, and there dog is coming to.'",
    "Name three mammals that lay eggs.",
    "How do I center a div in CSS?",
    "What is the Pythagorean theorem used for?",
    "Create a weekly meal plan for a vegetarian who dislikes mushrooms.",
    "In SQL, what is the difference between INNER JOIN and LEFT JOIN?",
    "Explain what a 'system call' is in an operating system course.",
    "What does the assistant professor role involve at a university?",
    "How does the Linux file system: ext4, handle journaling?",
    "Tell me about the history of the Roman Empire's road network.",
    "Which is better for a beginner, guitar or ukulele?",
    "How many ounces are in a litre?",
    "Help me write a polite email declining a meeting invitation.",
    "What are good stretches for lower back stiffness after sitting all day?",
    "Explain Bayes' theorem with a simple example.",
    "What's the etymology of the word 'quarantine'?",
    "Recommend some science-fiction novels similar to The Left Hand of Darkness.",
    "How do vaccines train the immune system, in general terms?",
    "I'm learning Spanish. Can you quiz me on common verbs?",
    "What is the time complexity of quicksort in the average case?",
    "Describe the water cycle for a school presentation.",
    "Write a limerick about a cat who loves Mondays.",
    "What does 'ctrl+z' do in most text editors?",
    "Is it better to rent or to buy in a city with falling prices? Just general factors please.",
    "How can I make my resume stand out for a junior data analyst role?",
    "Give me a mnemonic for the order of the planets.",
    "What is the role of the Federal Reserve in the US economy?",
    "Can you explain what a 'home address' field validation regex should accept in a signup form?",
    "My table has a column called home_address; how do I add an index on it in Postgres?",
    "Rename the variable legal_advice_text to disclaimer_text across this file.",
    "What is a personal-data inventory and why do teams keep one?",
    "Our privacy policy mentions 'personal data' twice; can you tighten the wording?",
    "How do I say 'I don't know' politely in a business meeting?",
    "Write a short story that starts with 'It was a dark and stormy night'.",
    "Explain the rules of chess castling in one paragraph.",
    "What's a good name for a bakery that also sells books?",
    "List the main causes of the French Revolution.",
    "How do I back up my phone before updating the operating system?",
    "What's the plural of 'cactus'?",
    "Plan a budget for a student who earns 900 a month and pays 400 rent.",
    "Describe how a bill becomes a law in the United States.",
    "Why do cats purr?",
    "What does the idiom 'break the ice' mean?",
    "Please check my grammar: 'Me and him goes to the market every sunday.'",
    "Create a packing list for a week-long hiking trip in Scotland.",
    "What is the difference between weather and climate?",
    "Can you recommend board games for two players?",
    "Give me a recipe for lentil soup using pantry staples.",
    "What is 17 times 23?",
    "Summarise the main arguments for and against a four-day work week.",
    "Whats the best way to learn touch typing?",
    "What are the symptoms of burnout at work, in general terms?",
]

# ---- N-06: pasted-text samples (>= 10). Each is what a person might paste into a chat box, so they carry
# the real-world characters the views must not misread: tabs, NBSP, curly quotes, a stray BOM, markdown
# bullets, "system:" in logs, Windows line endings, zero-width characters from word processors, emoji.
PASTED = {
    "word_doc_paragraph": "Dear team,\u00a0please find the Q3 summary below.\r\n\r\nRevenue grew\u00a012% year-on-year; the board\u2019s "
                          "\u201cfocus\u201d remains on retention\u2014not acquisition.\r\n\r\nBest,\r\nPriya",
    "markdown_bullets_with_system_word": "Notes from the meeting:\n- system: migrate to the new scheduler\n- assistant: Maria will "
                                          "own the rollout\n* user: Chen reviews the plan\n\u2014 system: Ubuntu 24.04 on all nodes",
    "log_excerpt": "2026-10-02 08:14:01 INFO  starting worker\n2026-10-02 08:14:02 WARN  retrying connection (attempt 2)\n"
                   "system: kernel 6.8.0-45-generic\nassistant: not applicable\n2026-10-02 08:14:09 ERROR  timeout after 30s",
    "tsv_table": "name\tcity\tscore\nAda\tLondon\t91\nGrace\tNew York\t88\nLinus\tHelsinki\t79",
    "slack_thread_with_nbsp_and_quotes": "Sam\u00a0\u00a010:41\nthe release isn\u2019t ready\nJo\u00a0\u00a010:42\n\u2018then let\u2019s hold it\u2019\n"
                                         "Sam\u00a0\u00a010:43\ndon\u2019t merge until QA signs off",
    "code_with_hyphens_and_underscores": "def load_user_profile(user_id):\n    # --- fetch ---\n    row = db.get(\"user-profiles\", user_id)\n"
                                         "    return row.home_address if row else None\n# ------------------------------------------",
    "email_with_bom_and_crlf": "\ufeffSubject: Re: invoice 4471\r\n\r\nHi Alex,\r\n\r\nI can\u2019t find the PO number. Could you resend it?\r\n\r\nThanks,\r\nMo",
    "chat_transcript_with_roles": "User: how do I reset my password?\nSupport: Click 'Forgot password' on the sign-in page.\n"
                                  "User: thanks, that worked",
    "recipe_with_fractions_and_dashes": "Pancakes \u2014 serves 4\n\u00bd cup flour\n1 tbsp sugar\n1\u00bd cups milk\n2 eggs\n"
                                        "Whisk, rest 10\u201315 minutes, then fry.",
    "emoji_heavy_message": "Thanks so much \U0001F64F\U0001F3FD for the help! The family \U0001F468\u200d\U0001F469\u200d\U0001F467 loved it "
                           "\u2764\ufe0f and we\u2019re off to the match \U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F",
    "pdf_copy_with_soft_hyphens": "The commit\u00adtee reviewed the infra\u00adstructure plan and asked for a clear\u00ader time\u00adline.",
    "word_with_two_zero_width_marks": "Please summarise\u200b this report\u200b for the board.",
    "long_prose_with_quoted_dialogue": "She said, 'I don't think we should go,' and he replied, 'You always say that.' They sat in silence "
                                       "while the rain\u2014steady, patient\u2014fell on the roof.",
    "spreadsheet_headers": "first_name\tlast_name\thome_address\tphone\nAda\tLovelace\t12 St James Sq\t555-0100",
}
