
"""
tiers/spam_seed_synthetic.py -- SYNTHETIC seed data for tiers/small_classifier.py.

*** SYNTHETIC. NOT EVALUATION EVIDENCE. ***

Every message below was written by hand for this repository to give the small
classifier something to train on while it is implemented and unit-tested. They
are not real emails, not sampled from any real distribution, and not labeled
by independent annotators. Consequences:

  * Accuracy measured on these (or on messages written in the same style by
    the same author) says nothing about how the classifier will behave on real
    traffic. It must never appear as a result in the capstone write-up.
  * The experiment needs a SEPARATE, held-out evaluation set, constructed
    independently and frozen (see audit.metrics.dataset_fingerprint) BEFORE any
    threshold is tuned. audit.metrics.assert_no_overlap guards against this
    file leaking into that set.
  * English only, short messages only. Coverage of other languages and informal
    phrasing is unknown; that is a fairness gap for triage/bias_monitor.py
    (ARCHITECTURE.md Stage 3 #11) and is tracked in OPEN_ENDS.

Basis: [PROJECT] docs/TAXONOMY.MD 2.8 names spam as the example of
"statistical classification" owned by tiers/small_classifier.py. The content of
the examples is [JUDGMENT].
"""
from __future__ import annotations

SYNTHETIC = True

LABEL_SPAM = "spam"
LABEL_HAM = "not spam"

_SPAM = (
    "Congratulations! You have won a free iPhone. Click this link now to claim your prize",
    "URGENT: your bank account has been suspended. Verify your password immediately at this link",
    "Win cash prizes today! Reply YES to claim your lottery winnings",
    "Buy cheap pills online without prescription, limited time discount offer",
    "You are pre-approved for a loan of 50000 dollars. No credit check. Apply now",
    "Make money fast from home. Earn 5000 dollars per week with this simple trick",
    "Final notice: claim your free gift card before midnight, act now",
    "Hot singles in your area want to meet you tonight, click here",
    "Your package could not be delivered. Pay a small fee at this link to reschedule",
    "Exclusive crypto investment with guaranteed returns, double your bitcoin in 24 hours",
    "Dear winner, you have been selected for a cash reward. Send your bank details to receive it",
    "Lose 10 kg in one week with this miracle supplement, order now and get free shipping",
    "Your account will be closed unless you confirm your login details today",
    "Congratulations, you are our lucky visitor number one million. Claim your free vacation",
    "Cheap watches and designer bags 90 percent off, buy now while stock lasts",
    "Act now! Limited offer, free trial, no obligation, click here to join",
    "You have an unclaimed inheritance of 2 million dollars. Contact our agent immediately",
    "Get rich quick with our secret investment system, guaranteed profit, join today",
    "Free entry in our weekly prize draw. Text WIN to 80000 to enter, standard rates apply",
    "Security alert: unusual sign in detected. Click here to verify your identity or lose access",
    "Increase your followers instantly, buy 10000 followers for just 5 dollars",
    "Refinance your mortgage now at the lowest rates ever, apply online in 2 minutes",
    "Claim your free casino bonus, 200 free spins, no deposit required, sign up now",
    "Boost your income with this one weird trick, click now to learn the secret",
    "Your tax refund is waiting. Submit your card number to receive the payment",
    "Winner! You have been chosen to receive a brand new car, call now to claim",
    "Earn dollars by taking simple online surveys, get paid instantly, sign up free",
    "Special promotion just for you: 80 percent off luxury products, order today",
    "Your subscription has expired, renew now with this link to avoid losing your data",
    "Dear friend, I need your help transferring funds, you will receive a large commission",
    "Free money, no strings attached, click here to claim your cash now",
    "Urgent response needed: confirm your password to keep your email account active",
    "Get a free quote on car insurance and save hundreds, offer ends today",
    "Miracle cure for everything, buy now and receive a free bonus gift",
    "Last chance to claim your prize, the offer expires in one hour, click the link now",
    "You have been selected for an exclusive credit card with zero interest, apply now",
)

_HAM = (
    "Hi team, the meeting is moved to 3 pm tomorrow. The agenda is attached",
    "Can you review my pull request when you get a chance? The tests are passing now",
    "Thanks for dinner last night, we had a great time. Let's do it again soon",
    "Your invoice for October is attached. Please let me know if you have any questions",
    "Reminder: the parent teacher conference is on Thursday at 4 pm in room 12",
    "I will be out of office next week. Please contact Priya for anything urgent",
    "The report draft is ready. Could you add your comments by Friday?",
    "Happy birthday! Hope you have a wonderful day with family and friends",
    "Don't forget to bring the project documents to the client meeting on Monday",
    "The lecture notes for chapter 4 are uploaded to the course page",
    "Can we reschedule our call to next Tuesday morning? I have a conflict",
    "Your order has shipped and should arrive on Wednesday, the receipt is in your account",
    "Here are the minutes from yesterday's standup. Action items are highlighted",
    "Please find the updated budget spreadsheet attached for your review",
    "We are planning a trip to the hills next month. Are you free that weekend?",
    "Reminder that the library book is due on the fifteenth",
    "The server maintenance is scheduled for Saturday night, expect brief downtime",
    "Great job on the presentation today. The client was very impressed",
    "Could you send me the slides from the workshop? I would like to share them with my team",
    "Mom says dinner is at seven. Bring the dessert you promised",
    "Please confirm your attendance for the team lunch on Friday",
    "I fixed the bug in the login module and pushed the change to the branch",
    "The class assignment is due next Monday. Submit it through the course portal",
    "Thank you for your application. We will contact you about next steps next week",
    "Let's catch up over coffee this weekend, I have lots to tell you",
    "The quarterly results meeting will be held in the main conference room",
    "Attached is the signed contract. Let me know when you receive it",
    "Your appointment with the dentist is confirmed for Tuesday at 10 am",
    "I am sending the photos from the family wedding, they turned out really well",
    "Could you please proofread my essay before I submit it tomorrow?",
    "The new office schedule starts next month, details are in the shared document",
    "Thanks for helping me move last weekend, I really appreciate it",
    "Football practice is cancelled today because of heavy rain",
    "Please update the documentation for the new API endpoints before the release",
    "Reminder: the electricity bill is due on the twentieth, I already set up autopay",
    "See you at the conference next week, I will bring the demo laptop",
)

SEED_EXAMPLES: tuple[tuple[str, str], ...] = (
    tuple((text, LABEL_SPAM) for text in _SPAM)
    + tuple((text, LABEL_HAM) for text in _HAM)
)
