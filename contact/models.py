"""Contact relay & moderation — docs/04-DATABASE-SCHEMA.md §10–11.

Models owned by this app (added in the schema phase, see ROADMAP.md):
ContactRequest (§10, doubles as rate-limit backend and abuse audit trail),
Report (§11), RecruiterApplication lives in accounts.

Rules that shape these models:
- The relay email is sent with Reply-To = sender's address; the recipient's
  email NEVER appears in any page or response.
- sender/recipient FKs are nullable + SET NULL (GDPR anonymization while
  keeping the abuse trail).
- Rate limit = count of contact_requests rows per sender per 24h.
"""
