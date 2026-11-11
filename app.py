from datetime import datetime, timezone

import stripe
import streamlit as st
from openai import OpenAI
from supabase import create_client

FREE_LIMIT = 3

# 1. Page Configuration (called once only)
st.set_page_config(page_title="Instant Real Estate Copywriter", page_icon="🏠", layout="wide")

# 2. Load secrets and clients
try:
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
    stripe.api_key = st.secrets["STRIPE_SECRET_KEY"]
    BASIC_PRICE_ID = st.secrets["STRIPE_BASIC_PRICE_ID"]
    PRO_PRICE_ID = st.secrets["STRIPE_PRO_PRICE_ID"]
    APP_URL = st.secrets["APP_URL"]
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_KEY"]
except Exception:
    st.error(f"Setup Error: {type(e).__name__}: {e}")
   # st.error("Setup Error: one or more secrets are missing. See secrets_template.toml.")
    st.stop()

# Plan definitions: one place to change prices-to-caps
PLANS = {
    BASIC_PRICE_ID: {"name": "Basic", "cap": 30, "label": "Basic: $29/mo, 30 generations"},
    PRO_PRICE_ID: {"name": "Pro", "cap": 150, "label": "Pro: $59/mo, 150 generations"},
}


@st.cache_resource
def get_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def fmt_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%b %d")


# 3. Login gate: nothing below runs unless the user is signed in
st.title("🏠 Real Estate Copy Generator")

if not st.user.is_logged_in:
    st.write("Turn raw property notes into a complete marketing suite instantly.")
    st.write(f"Sign in to get **{FREE_LIMIT} free generations**.")
    st.button("Sign in with Google", type="primary", on_click=st.login)
    st.stop()

email = (st.user.email or "").strip().lower()
if not email:
    st.error("Your Google account did not return an email address.")
    st.stop()

st.write("Turn raw property notes into a complete marketing suite instantly.")


# 4. Stripe: the source of truth for plan and billing period
def _field(obj, name):
    """Read a field from a Stripe object. Newer stripe-python versions are not
    dicts (no .get), so use bracket access and treat a missing key as None."""
    try:
        return obj[name]
    except (KeyError, AttributeError, TypeError):
        return None


def billing_period(sub):
    """Returns (start, end) unix timestamps. Newer Stripe API versions keep
    these on the subscription item instead of the subscription itself."""
    start = _field(sub, "current_period_start")
    end = _field(sub, "current_period_end")
    if start is None or end is None:
        item = sub["items"]["data"][0]
        if start is None:
            start = _field(item, "current_period_start")
        if end is None:
            end = _field(item, "current_period_end")
    return start or 0, end or 0


@st.cache_data(ttl=60, show_spinner=False)
def subscription_info(user_email: str):
    """Cached for 60 seconds per email."""
    info = {"active": False, "customer_id": None, "plan": None, "cap": 0, "start": 0, "end": 0}
    customers = stripe.Customer.list(email=user_email, limit=10)
    for c in customers.data:
        if info["customer_id"] is None:
            info["customer_id"] = c.id
        subs = stripe.Subscription.list(customer=c.id, status="all", limit=10)
        for s in subs.data:
            if s.status not in ("active", "trialing"):
                continue
            price_id = s["items"]["data"][0]["price"]["id"]
            plan = PLANS.get(price_id, PLANS[BASIC_PRICE_ID])  # unknown price -> Basic cap
            if plan["cap"] > info["cap"]:  # if someone has two, the bigger plan wins
                start, end = billing_period(s)
                info.update(active=True, customer_id=c.id, plan=plan["name"],
                            cap=plan["cap"], start=start, end=end)
    return info


try:
    sub = subscription_info(email)
except Exception as e:
    st.error(f"Could not verify your subscription right now. Please try again. ({e})")
    st.stop()

is_subscriber = sub["active"]
customer_id = sub["customer_id"]


# 5. Supabase: the only data we store (usage counters per email)
def get_usage(user_email: str):
    res = (
        get_supabase()
        .table("usage")
        .select("free_used, paid_used, paid_period")
        .eq("email", user_email)
        .execute()
    )
    if res.data:
        row = res.data[0]
        return row["free_used"], row["paid_used"], row["paid_period"]
    return 0, 0, 0


def save_free_used(user_email: str, count: int):
    get_supabase().table("usage").upsert({"email": user_email, "free_used": count}).execute()


def save_paid_used(user_email: str, count: int, period_start: int):
    get_supabase().table("usage").upsert(
        {"email": user_email, "paid_used": count, "paid_period": period_start}
    ).execute()


free_used, paid_used_raw, paid_period = get_usage(email)
# Paid usage only counts if it belongs to the current billing period; a new period resets to 0
paid_used = paid_used_raw if paid_period == sub["start"] else 0

if is_subscriber:
    remaining = max(sub["cap"] - paid_used, 0)
else:
    remaining = max(FREE_LIMIT - free_used, 0)
locked = remaining == 0


# 6. Checkout and billing portal helpers
def upgrade_box(key: str):
    for price_id, plan in PLANS.items():
        if st.button(f"Subscribe: {plan['label']}", key=f"sub_{key}_{plan['name']}",
                     type="primary", use_container_width=True):
            session = stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": price_id, "quantity": 1}],
                customer_email=email,  # locks checkout to the signed-in email
                success_url=APP_URL,
                cancel_url=APP_URL,
            )
            st.session_state["checkout_url"] = session.url
    if st.session_state.get("checkout_url"):
        st.link_button("Continue to secure checkout →", st.session_state["checkout_url"])


def manage_box(key: str, link_label: str):
    if customer_id and st.button("Manage subscription", key=f"manage_{key}"):
        portal = stripe.billing_portal.Session.create(customer=customer_id, return_url=APP_URL)
        st.session_state["portal_url"] = portal.url
    if customer_id and st.session_state.get("portal_url"):
        st.link_button(link_label, st.session_state["portal_url"])


# 7. Sidebar: account status
with st.sidebar:
    st.subheader("Account")
    st.caption(email)
    if is_subscriber:
        st.success(f"{sub['plan']} plan active ✅")
        st.write(f"Used **{paid_used} of {sub['cap']}** this month")
        if sub["end"]:
            st.caption(f"Resets {fmt_date(sub['end'])}")
        manage_box("sidebar", "Open billing portal →")
    else:
        st.write(f"Free generations left: **{remaining} of {FREE_LIMIT}**")
        if not locked:
            upgrade_box("sidebar")
        manage_box("sidebar", "Open billing portal →")
    if st.button("Refresh status"):
        subscription_info.clear()
        st.session_state.pop("checkout_url", None)
        st.session_state.pop("portal_url", None)
        st.rerun()
    st.button("Sign out", on_click=st.logout)

if locked:
    if is_subscriber:
        reset = f" Your allowance resets on {fmt_date(sub['end'])}." if sub["end"] else ""
        st.warning(f"You've used all {sub['cap']} generations on the {sub['plan']} plan.{reset}")
        if sub["plan"] == "Basic":
            st.write("Need more? Switch to Pro (150 generations/month) in the billing portal.")
            manage_box("main", "Open billing portal to switch plans →")
    else:
        st.warning(f"You've used your {FREE_LIMIT} free generations. Choose a plan to keep generating.")
        upgrade_box("main")

# 8. User Input Section
st.subheader("Property Details")
raw_description = st.text_area(
    "Paste your raw property notes, bullet points, or MLS data here:",
    height=200,
    placeholder="Example: 3 bed, 2.5 bath in North Austin. Built 2018. Quartz countertops, huge backyard, cul-de-sac. Walkable to coffee shop...",
)

tone = st.selectbox("Select Marketing Tone", ["Enthusiastic & Luxury", "Casual & Warm", "Professional & Urgent"])

# 9. Generation Logic
if st.button("Generate Marketing Suite ✨", type="primary", disabled=locked, key="generate"):
    if not raw_description.strip():
        st.error("Please provide some property details first.")
    else:
        system_prompt = (
            "You are an expert real estate copywriter. Your job is to take raw property information "
            "and convert it into highly compelling marketing materials. Maintain a tone that is "
            f"{tone}. Structure your output strictly with clear markdown headers for each requested piece."
            "Use only facts from the notes: never invent features, numbers or "
            "neighborhood claims (use a placeholder where a detail is missing). "
            "Follow Fair Housing rules: describe the property, not the ideal buyer, and "
             "never reference race, religion, family status, disability or other "
             "protected classes."

        )

        user_prompt = f"""
        Analyze these property notes and generate the following items:

        1. **Post 1: Instagram (The Hook)** - Visually descriptive, heavy use of relevant emojis, clear Call to Action (CTA) to DM for details, includes relevant hashtags.
        2. **Post 2: Facebook (The Story)** - A bit longer, focuses on the lifestyle / neighborhood vibe, family-friendly, clear CTA.
        3. **Post 3: LinkedIn (The Investment)** - Focuses on the market value, architectural highlights, or investment potential. Professional tone.
        4. **Post 4: TikTok/Reels Script** - A short, 30-second punchy video script outlining what to show on screen and what to say (Voiceover).
        5. **Post 5: Just Listed Bulleted Summary** - A fast, scannable list of top features for quick reading.
        6. **Email Newsletter Blast** - Includes a compelling Subject Line, a warm greeting, body copy expanding on the property benefits, Open House details placeholder, and a strong CTA button text.
        7. **Print Flyer Text** - Bold headline, property summary, bulleted specs, and a footer placeholder for Realtor Contact Info.

        ---
        PROPERTY NOTES:
        {raw_description}
        """

        with st.spinner("AI is crafting your copy..."):
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.7,
                )

                # Count the use only after a successful generation
                if is_subscriber:
                    save_paid_used(email, paid_used + 1, sub["start"])
                    left = max(sub["cap"] - (paid_used + 1), 0)
                    note = f"Generations left this month: {left} of {sub['cap']}"
                else:
                    save_free_used(email, free_used + 1)
                    left = max(FREE_LIMIT - (free_used + 1), 0)
                    note = f"Free generations left: {left} of {FREE_LIMIT}"

                st.success("Generation Complete!")
                st.info(note)
                st.divider()
                st.markdown(response.choices[0].message.content)

            except Exception as e:
                st.error(f"An error occurred: {e}")
