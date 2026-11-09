"""
Instant Real Estate Copywriter: Streamlit + Supabase + Stripe (via Make.com)

Flow
  Guest (no account)  -> 3 free generations, tracked server-side by a browser
                         cookie id (+ an IP safety net)
  Sign up / log in    -> guest usage carries over into the account
  Limit reached       -> sign up (guests) or upgrade (free accounts)
  Paid                -> Stripe -> Make.com -> Supabase flips the tier
"""
import hashlib
import re
import uuid
from datetime import datetime, timedelta
from urllib.parse import quote

import streamlit as st
from openai import OpenAI
from streamlit_cookies_controller import CookieController
from supabase import Client, create_client

st.set_page_config(
    page_title="Instant Real Estate Copywriter",
    page_icon="🏠",
    layout="wide",
)

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
TIER_LIMITS = {"free": 3, "basic": 30, "pro": 150}
TIER_LABELS = {"free": "Free", "basic": "Basic Agent", "pro": "Power Broker"}

GUEST_LIMIT = 3          # free generations without an account
GUEST_IP_LIMIT = 12      # safety net: max guest generations per IP / 30 days
MAX_INPUT_CHARS = 4000
MIN_PASSWORD_LEN = 8

GUEST_COOKIE = "re_guest_id"
REFRESH_COOKIE = "re_refresh_token"
GUEST_COOKIE_DAYS = 365
REFRESH_COOKIE_DAYS = 30

MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = (
    "You are an expert real estate copywriter. Your job is to take raw property "
    "information and convert it into highly compelling marketing materials. "
    "Maintain a tone that is {tone}. Structure your output strictly with clear "
    "markdown headers for each requested piece. "
    "Use only facts from the notes: never invent features, numbers or "
    "neighborhood claims (use a placeholder where a detail is missing). "
    "Follow Fair Housing rules: describe the property, not the ideal buyer, and "
    "never reference race, religion, family status, disability or other "
    "protected classes."
)

USER_PROMPT = """
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
{notes}
"""

REQUIRED_SECRETS = [
    "OPENAI_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",      # used ONLY for sign up / log in
    "SUPABASE_SERVICE_KEY",   # server-side only, used for all database work
    "STRIPE_BASIC_LINK",
    "STRIPE_PRO_LINK",
]


def secret(name: str, default=None):
    try:
        return st.secrets[name]
    except Exception:
        return default


missing = [k for k in REQUIRED_SECRETS if not secret(k)]
if missing:
    st.error(
        "Setup error: add these to your Streamlit secrets: " + ", ".join(missing)
    )
    st.stop()


# ----------------------------------------------------------------------
# Connections
# ----------------------------------------------------------------------
@st.cache_resource
def get_db() -> Client:
    """Service-role client. Never used for auth calls, so it never gets
    switched to a user token. Bypasses RLS; only ever runs on the server."""
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_SERVICE_KEY"])


@st.cache_resource
def get_openai() -> OpenAI:
    return OpenAI(api_key=st.secrets["OPENAI_API_KEY"])


def get_auth_client() -> Client:
    """Fresh anon client per auth call (sign up / log in / refresh)."""
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])


# ----------------------------------------------------------------------
# Session state
# ----------------------------------------------------------------------
def init_state() -> None:
    defaults = {
        "user": None,            # {"id": ..., "email": ...}
        "access_token": None,
        "restore_tried": False,
        "cookie_ops": [],        # queued browser-cookie writes
        "last_output": None,     # generated copy survives reruns
        "auth_error": None,
        "auth_notice": None,
        "show_auth": False,
        "auth_mode": "Create account",
        "guest_blocked": False,  # server said "no more guest generations"
        "poll_count": 0,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


# ----------------------------------------------------------------------
# Browser cookies
#   Reading  -> st.context.cookies (available instantly on page load)
#   Writing  -> queued, then flushed through a tiny JS component
# ----------------------------------------------------------------------
def queue_cookie(op: str, name: str, value: str | None = None, days: int = 0) -> None:
    st.session_state["cookie_ops"].append((op, name, value, days))


def flush_cookie_ops() -> None:
    ops = st.session_state["cookie_ops"]
    if not ops:
        return
    st.session_state["cookie_ops"] = []
    # hide the zero-height iframes the cookie component renders
    st.html('<style>.element-container:has(iframe[height="0"]){display:none;}</style>')
    controller = CookieController(key="cookie_ctl")
    for op, name, value, days in ops:
        if op == "set":
            controller.set(
                name,
                value,
                max_age=days * 86400,
                expires=datetime.now() + timedelta(days=days),
                same_site="lax",
            )
        else:
            try:
                controller.remove(name, same_site="lax")
            except KeyError:
                pass  # the JS removal already ran; only the local copy was missing


def get_cookie(name: str) -> str | None:
    try:
        return st.context.cookies.get(name)
    except Exception:
        return None


def ensure_guest_id() -> str:
    ss = st.session_state
    if "guest_id" in ss:
        return ss["guest_id"]
    guest_id = None
    raw = get_cookie(GUEST_COOKIE)
    if raw:
        try:
            guest_id = str(uuid.UUID(raw))  # cookie is client-controlled: validate
        except ValueError:
            guest_id = None
    if guest_id is None:
        guest_id = str(uuid.uuid4())
        queue_cookie("set", GUEST_COOKIE, guest_id, GUEST_COOKIE_DAYS)
    ss["guest_id"] = guest_id
    return guest_id


def client_ip_hash() -> str | None:
    """Salted hash of the visitor's IP (best effort; never stored raw)."""
    ip = None
    try:
        forwarded = st.context.headers.get("X-Forwarded-For", "")
        ip = forwarded.split(",")[0].strip() if forwarded else None
        ip = ip or getattr(st.context, "ip_address", None)
    except Exception:
        ip = None
    if not ip:
        return None
    salt = secret("IP_SALT", "")
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()


# ----------------------------------------------------------------------
# Auth (callbacks run BEFORE the script body, so no st.rerun() is needed)
# ----------------------------------------------------------------------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def friendly_auth_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "invalid login" in msg or "invalid credentials" in msg:
        return "Incorrect email or password."
    if "not confirmed" in msg:
        return "Please confirm your email first. Check your inbox for the link."
    if "already registered" in msg or "already exists" in msg:
        return "An account with this email already exists. Please log in."
    if "rate limit" in msg or "too many" in msg:
        return "Too many attempts. Please wait a few minutes and try again."
    if "password" in msg and ("weak" in msg or "least" in msg):
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    return "Something went wrong. Please try again."


def clear_auth_messages() -> None:
    st.session_state["auth_error"] = None
    st.session_state["auth_notice"] = None


def finish_login(session, user) -> None:
    ss = st.session_state
    ss["user"] = {"id": str(user.id), "email": user.email}
    ss["access_token"] = session.access_token
    ss["last_output"] = None
    ss["show_auth"] = False
    ss["poll_count"] = 0
    queue_cookie("set", REFRESH_COOKIE, session.refresh_token, REFRESH_COOKIE_DAYS)
    # carry guest usage into the account (no-op if already claimed)
    try:
        get_db().rpc(
            "claim_guest_usage",
            {"p_user_id": str(user.id), "p_guest_id": ensure_guest_id()},
        ).execute()
    except Exception as exc:  # fail open, but leave a trace in the server logs
        print(f"claim_guest_usage failed: {exc}")


def handle_login() -> None:
    ss = st.session_state
    clear_auth_messages()
    email = (ss.get("login_email") or "").strip().lower()
    password = ss.get("login_password") or ""
    if not email or not password:
        ss["auth_error"] = "Enter your email and password."
        return
    try:
        res = get_auth_client().auth.sign_in_with_password(
            {"email": email, "password": password}
        )
        finish_login(res.session, res.user)
    except Exception as exc:
        ss["auth_error"] = friendly_auth_error(exc)


def handle_signup() -> None:
    ss = st.session_state
    clear_auth_messages()
    email = (ss.get("signup_email") or "").strip().lower()
    password = ss.get("signup_password") or ""
    if not EMAIL_RE.match(email):
        ss["auth_error"] = "Please enter a valid email address."
        return
    if len(password) < MIN_PASSWORD_LEN:
        ss["auth_error"] = f"Password must be at least {MIN_PASSWORD_LEN} characters."
        return

    credentials = {"email": email, "password": password}
    app_url = secret("APP_URL")
    if app_url:
        credentials["options"] = {"email_redirect_to": app_url}

    try:
        res = get_auth_client().auth.sign_up(credentials)
    except Exception as exc:
        ss["auth_error"] = friendly_auth_error(exc)
        return

    if res.session and res.user:  # email confirmation is switched off
        finish_login(res.session, res.user)
        return

    ss["login_email"] = email
    ss["auth_mode"] = "Log in"
    if res.user is not None and not (res.user.identities or []):
        # Supabase hides "already registered" behind a fake success
        ss["auth_error"] = "An account with this email already exists. Please log in."
    else:
        ss["auth_notice"] = (
            "Account created! Check your email to confirm it, then log in here."
        )


def handle_logout() -> None:
    ss = st.session_state
    token = ss.get("access_token")
    if token:
        try:
            get_db().auth.admin.sign_out(token, "local")  # revoke this session only
        except Exception:
            pass
    queue_cookie("remove", REFRESH_COOKIE)
    ss["user"] = None
    ss["access_token"] = None
    ss["last_output"] = None
    ss["show_auth"] = False
    ss["guest_blocked"] = False
    clear_auth_messages()


def restore_session() -> None:
    """After a browser refresh, log the user back in from their refresh cookie."""
    ss = st.session_state
    if ss["user"] or ss["restore_tried"]:
        return
    ss["restore_tried"] = True
    refresh_token = get_cookie(REFRESH_COOKIE)
    if not refresh_token:
        return
    try:
        res = get_auth_client().auth.refresh_session(refresh_token)
        if res.session and res.user:
            finish_login(res.session, res.user)  # also stores the rotated token
        else:
            queue_cookie("remove", REFRESH_COOKIE)
    except Exception:
        pass  # expired/invalid/offline: they simply log in again


def open_auth(mode: str) -> None:
    clear_auth_messages()
    st.session_state["show_auth"] = True
    st.session_state["auth_mode"] = mode


def close_auth() -> None:
    clear_auth_messages()
    st.session_state["show_auth"] = False


# ----------------------------------------------------------------------
# Data access
# ----------------------------------------------------------------------
def load_profile(user: dict) -> tuple[str, int]:
    db = get_db()
    res = (
        db.table("profiles")
        .select("subscription_tier, generations_used")
        .eq("id", user["id"])
        .limit(1)
        .execute()
    )
    if res.data:
        row = res.data[0]
    else:
        # self-heal: accounts created before the signup trigger existed
        db.table("profiles").upsert(
            {"id": user["id"], "email": user["email"]}, on_conflict="id"
        ).execute()
        row = {"subscription_tier": "free", "generations_used": 0}
    tier = row["subscription_tier"] if row["subscription_tier"] in TIER_LIMITS else "free"
    return tier, int(row["generations_used"])


def load_guest_remaining(guest_id: str) -> int:
    if st.session_state["guest_blocked"]:
        return 0
    res = (
        get_db()
        .table("guest_usage")
        .select("generations_used, claimed_by")
        .eq("guest_id", guest_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return GUEST_LIMIT
    row = res.data[0]
    if row["claimed_by"]:
        return 0  # their free allowance moved into an account
    return max(0, GUEST_LIMIT - int(row["generations_used"]))


# ----------------------------------------------------------------------
# Generation: reserve atomically -> call AI -> refund if it fails
# ----------------------------------------------------------------------
def reserve(user: dict | None, limit: int) -> bool:
    db = get_db()
    if user:
        res = db.rpc(
            "reserve_generation", {"p_user_id": user["id"], "p_limit": limit}
        ).execute()
    else:
        res = db.rpc(
            "reserve_guest_generation",
            {
                "p_guest_id": st.session_state["guest_id"],
                "p_ip_hash": client_ip_hash(),
                "p_limit": GUEST_LIMIT,
                "p_ip_limit": GUEST_IP_LIMIT,
            },
        ).execute()
    return res.data is not None and int(res.data) >= 0


def refund(user: dict | None) -> None:
    try:
        if user:
            get_db().rpc("refund_generation", {"p_user_id": user["id"]}).execute()
        else:
            get_db().rpc(
                "refund_guest_generation", {"p_guest_id": st.session_state["guest_id"]}
            ).execute()
    except Exception as exc:
        print(f"refund failed: {exc}")


def generate_copy(raw: str, tone: str) -> str:
    resp = get_openai().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(tone=tone)},
            {"role": "user", "content": USER_PROMPT.format(notes=raw)},
        ],
        temperature=0.7,
        max_tokens=4000,  # room for all 7 deliverables
        timeout=60,
    )
    return (resp.choices[0].message.content or "").strip()


def run_generation(user: dict | None, limit: int, raw: str, tone: str) -> None:
    ss = st.session_state
    raw = raw.strip()[:MAX_INPUT_CHARS]
    with st.spinner("AI is crafting your copy..."):
        try:
            allowed = reserve(user, limit)
        except Exception:
            st.error("We couldn't reach the database. Please try again in a moment.")
            return
        if not allowed:
            if not user:
                ss["guest_blocked"] = True
            st.rerun()  # re-render: shows the limit screen
        try:
            text = generate_copy(raw, tone)
            if not text:
                raise RuntimeError("empty response")
        except Exception:
            refund(user)  # a failed AI call never costs the user a generation
            st.error("The AI service had a problem. You were not charged. Please try again.")
            return
    ss["last_output"] = text  # saved BEFORE the rerun so it survives it
    st.rerun()  # refresh the counters


# ----------------------------------------------------------------------
# UI pieces
# ----------------------------------------------------------------------
def checkout_url(base: str, user: dict) -> str:
    """Tag the Stripe link with the user's id so the webhook knows who paid."""
    sep = "&" if "?" in base else "?"
    return (
        f"{base}{sep}client_reference_id={user['id']}"
        f"&prefilled_email={quote(user['email'], safe='')}"
    )


def portal_url(user: dict) -> str | None:
    base = secret("STRIPE_PORTAL_LINK")
    if not base:
        return None
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}prefilled_email={quote(user['email'], safe='')}"


def render_sidebar_user(user: dict, tier: str, used: int) -> None:
    limit = TIER_LIMITS[tier]
    sb = st.sidebar
    sb.header("🏠 Your Account")
    sb.markdown(f"**{user['email']}**")
    sb.markdown(f"Plan: **{TIER_LABELS[tier]}**")
    shown = min(used, limit)
    sb.progress(min(1.0, max(0.0, shown / limit)) if limit else 0.0)  # fix #6
    period = "this month" if tier != "free" else "(free allowance)"
    sb.caption(f"{shown} / {limit} generations used {period}")
    link = portal_url(user)
    if tier != "free" and link:
        sb.link_button("Manage subscription", link)
    sb.button("Log out", on_click=handle_logout)


def render_sidebar_guest(remaining: int) -> None:
    sb = st.sidebar
    sb.header("🏠 Welcome")
    sb.markdown("**Guest**: free trial")
    used = GUEST_LIMIT - remaining
    sb.progress(min(1.0, max(0.0, used / GUEST_LIMIT)))
    sb.caption(f"{used} / {GUEST_LIMIT} free generations used")
    sb.button("Log in", on_click=open_auth, args=("Log in",), key="sb_login")
    sb.button("Create account", on_click=open_auth, args=("Create account",), key="sb_signup")


def render_auth_panel(headline: str | None = None, allow_back: bool = False) -> None:
    ss = st.session_state
    if headline:
        st.subheader(headline)
    if ss["auth_notice"]:
        st.success(ss["auth_notice"])
    if ss["auth_error"]:
        st.error(ss["auth_error"])

    st.radio(
        "Account",
        ["Create account", "Log in"],
        key="auth_mode",
        horizontal=True,
        label_visibility="collapsed",
        on_change=clear_auth_messages,
    )
    if ss["auth_mode"] == "Create account":
        with st.form("signup_form"):
            st.text_input("Email address", key="signup_email")
            st.text_input(
                "Password",
                type="password",
                key="signup_password",
                help=f"At least {MIN_PASSWORD_LEN} characters.",
            )
            st.form_submit_button("Create account", type="primary", on_click=handle_signup)
    else:
        with st.form("login_form"):
            st.text_input("Email address", key="login_email")
            st.text_input("Password", type="password", key="login_password")
            st.form_submit_button("Log in", type="primary", on_click=handle_login)
    if allow_back:
        st.button("← Back to the free generator", on_click=close_auth)


def plan_card(col, title: str, detail: str, price: str, url: str | None, primary=False) -> None:
    with col:
        with st.container(border=True):
            st.markdown(f"**{title}**\n\n{detail}\n\n**{price}**")
            if url:
                st.link_button(f"Choose {title}", url, type="primary" if primary else "secondary")


def render_plan_cards(user: dict | None, tier: str = "free") -> None:
    col1, col2 = st.columns(2)
    basic = checkout_url(st.secrets["STRIPE_BASIC_LINK"], user) if user else None
    pro = checkout_url(st.secrets["STRIPE_PRO_LINK"], user) if user else None
    if tier == "free":
        plan_card(col1, "Basic Agent", "Up to 30 properties / month", "$29/mo", basic)
        plan_card(col2, "Power Broker ⭐", "Up to 150 properties / month", "$59/mo", pro, primary=True)
    elif tier == "basic":
        plan_card(col1, "Power Broker ⭐", "Up to 150 properties / month", "$59/mo", None)


def render_output() -> None:
    text = st.session_state.get("last_output")
    if not text:
        return
    st.success("Generation Complete!")
    st.divider()
    st.markdown(text)


def render_generator() -> tuple[str, str]:
    st.subheader("Property Details")
    raw = st.text_area(
        "Paste your raw property notes, bullet points, or MLS data here:",
        height=200,
        max_chars=MAX_INPUT_CHARS,
        key="raw_description",
        placeholder=(
            "Example: 3 bed, 2.5 bath in North Austin. Built 2018. Quartz "
            "countertops, huge backyard, cul-de-sac. Walkable to coffee shop..."
        ),
    )
    tone = st.selectbox(
        "Select Marketing Tone",
        ["Enthusiastic & Luxury", "Casual & Warm", "Professional & Urgent"],
        key="tone",
    )
    return raw, tone


@st.fragment(run_every=3)
def wait_for_activation(user: dict) -> None:
    """After checkout, poll briefly until the webhook has upgraded the plan."""
    ss = st.session_state
    ss["poll_count"] += 1
    tier, _ = load_profile(user)
    if tier != "free" or ss["poll_count"] > 20:
        st.rerun()  # full rerun: shows the new plan, or the "refresh" button


# ----------------------------------------------------------------------
# Screens
# ----------------------------------------------------------------------
def guest_screen(remaining: int) -> None:
    ss = st.session_state
    if ss["show_auth"]:
        render_auth_panel(allow_back=remaining > 0)
        return

    if remaining <= 0:
        render_output()
        st.warning("🎁 You've used your 3 free generations.")
        render_auth_panel(
            headline="Create a free account to continue, or log in",
        )
        st.markdown("#### Then pick a plan to keep going")
        render_plan_cards(None)
        st.caption("Sign up first so your plan is linked to your account.")
        return

    st.info(
        f"🎁 **Try it free**: {remaining} of {GUEST_LIMIT} free generations left. "
        "No account needed."
    )
    c1, c2, _ = st.columns([1, 1.3, 2])
    c1.button("Create account", on_click=open_auth, args=("Create account",), key="top_signup")
    c2.button("I already have an account", on_click=open_auth, args=("Log in",), key="top_login")

    raw, tone = render_generator()
    if st.button("Generate Marketing Suite ✨", type="primary"):
        if not raw.strip():
            st.error("Please provide some property details first.")
        else:
            run_generation(None, GUEST_LIMIT, raw, tone)
    render_output()


def user_screen(user: dict, tier: str, used: int) -> None:
    limit = TIER_LIMITS[tier]

    if st.query_params.get("checkout") == "success":
        if tier == "free":
            st.info("🎉 Payment received! Activating your plan. This usually takes a few seconds.")
            if st.session_state["poll_count"] <= 20:  # poll ~1 minute, then stop
                wait_for_activation(user)
            else:
                st.warning("Still activating. Click below to check again.")
                if st.button("Refresh my plan"):
                    st.session_state["poll_count"] = 0
                    st.rerun()
        else:
            st.success(f"You're now on the {TIER_LABELS[tier]} plan. Enjoy!")
            st.query_params.clear()

    if used >= limit:
        render_output()
        if tier == "free":
            st.error("🚨 **You've used all your free generations.**")
            st.markdown("### 💎 Choose a plan to continue")
            render_plan_cards(user, "free")
        elif tier == "basic":
            st.error(f"🚨 **You've used all {limit} generations on your Basic plan this month.**")
            link = portal_url(user)
            if link:
                st.link_button("Upgrade to Power Broker (150/mo)", link, type="primary")
            st.caption("Your allowance also resets when your subscription renews.")
        else:
            st.error(f"🚨 **You've used all {limit} generations this month.**")
            st.caption("Your allowance resets when your subscription renews.")
        return

    raw, tone = render_generator()
    if st.button("Generate Marketing Suite ✨", type="primary"):
        if not raw.strip():
            st.error("Please provide some property details first.")
        else:
            run_generation(user, limit, raw, tone)
    render_output()


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main() -> None:
    init_state()
    restore_session()
    guest_id = ensure_guest_id()
    flush_cookie_ops()  # writes any queued cookies to the browser

    st.title("🏠 Real Estate Copy Generator")
    st.write("Turn raw property notes into a complete marketing suite instantly.")
    user = st.session_state["user"]

    try:
        if user:
            tier, used = load_profile(user)
        else:
            remaining = load_guest_remaining(guest_id)
    except Exception as e:
        st.error("We couldn't reach the database. Please try again in a moment.")
        st.exception(e) ## temporary: shows the real error on the page
        st.stop()

    if user:
        render_sidebar_user(user, tier, used)
        user_screen(user, tier, used)
    else:
        render_sidebar_guest(remaining)
        if st.query_params.get("checkout") == "success":
            st.info("🎉 Payment received! Log in to the account you upgraded to see your plan.")
        guest_screen(remaining)


main()
