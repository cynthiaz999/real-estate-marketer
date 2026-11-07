import streamlit as st
from openai import OpenAI
from supabase import create_client, Client

# 1. Page Configuration
st.set_page_config(
    page_title="PropCopyAI - 5-Second Real Estate Marketing Campaigns", 
    page_icon="🏠", 
    layout="wide"
)

# 2. Establish Secure Connections
try:
    openai_api_key = st.secrets["OPENAI_API_KEY"]
    client = OpenAI(api_key=openai_api_key)
    supabase_url = st.secrets["SUPABASE_URL"]
    supabase_key = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(supabase_url, supabase_key)
except Exception:
    st.error("Setup Error: Please configure your Streamlit Secrets.")
    st.stop()

TIER_LIMITS = {"free": 3, "basic": 30, "pro": 150}

# 3. Session State & URL Parameter Route Catching
if "user_email" not in st.session_state:
    # Check if user is returning from Stripe with an email parameter
    if "email" in st.query_params:
        st.session_state["user_email"] = st.query_params["email"]
    else:
        st.session_state["user_email"] = None

# ==========================================
# 🛑 SCREEN A: THE PUBLIC LANDING PAGE
# ==========================================
if st.session_state["user_email"] is None:
    # Simple top bar navigation for existing users to sign in
    col_logo, col_login = st.columns([4, 1])
    with col_logo:
        st.subheader("🏠 PropCopyAI")
    with col_login:
        # Subtle expander allowing existing users to jump straight past the landing page
        with st.popover("🔑 Existing User Login"):
            existing_email = st.text_input("Enter your account email:")
            if st.button("Unlock My Account"):
                profile_check = supabase.table("profiles").select("*").eq("email", existing_email.strip()).execute()
                if profile_check.data:
                    st.session_state["user_email"] = existing_email.strip()
                    st.rerun()
                else:
                    st.error("Account email not found.")

    st.divider()

    # Hero Section
    st.markdown("<h1 style='text-align: center;'>Stop writing real estate copy.</h1>", unsafe_allow_html=True)
    st.markdown("<h3 style='text-align: center; color: #4F46E5;'>Let AI build your 7-part marketing campaign in 5 seconds.</h3>", unsafe_allow_html=True)
    st.write("")
    
    # Core Call to Action Button
    col_cb1, col_cb2, col_cb3 = st.columns([1, 1, 1])
    with col_cb2:
        # Link this button to your Stripe Pricing/Checkout Link
        st.link_button(
            "🚀 Start Your 7-Day Free Trial", 
            "https://stripe.com", 
            use_container_width=True,
            type="primary"
        )
    st.write("")
    st.divider()

    # The Realtor Pain Points Section
    st.markdown("### 😩 Why Realtors Waste Hours Every Week")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("#### 1. Writer's Block")
        st.write("Staring at a blank screen trying to make a standard 3-bed suburban home sound like a hidden paradise.")
    with col2:
        st.markdown("#### 2. Fragmented Formats")
        st.write("Rewriting the exact same property data over and over to fit MLS rules, Facebook guidelines, and email templates.")
    with col3:
        st.markdown("#### 3. Lead Delays")
        st.write("Waiting days for an expensive copywriter or marketing assistant to return files while your listing goes cold.")

    st.divider()

    # Interactive Example Output Showcase
    st.markdown("### ✨ See What You'll Generate Instantly")
    with st.expander("🔍 Click to preview a sample 7-part suite output"):
        st.markdown("""
        ### 📋 1. Optimized MLS Description
        *Stunning North Austin remodel featuring custom quartz counters, open-concept hosting spaces...*
        
        ### 📱 2. Instagram & Facebook Hook
        *🏡 JUST LISTED! Skip the waitlist for this Austin gem. Swipe left for the kitchen views! #AustinRealEstate*
        
        ### 📧 3. Local Broker Email Blast
        *Subject: Pocket listing energy in North Austin - Commission matching active...*
        """)
    st.stop()  # Enforces that nobody goes past this line without being authenticated!


# ==========================================
# 🎉 SCREEN B: THE PRIVATE GENERATION TOOL
# ==========================================
# This section only runs if st.session_state["user_email"] holds a valid value

user_email = st.session_state["user_email"]

# Fetch profile details
try:
    profile_data = supabase.table("profiles").select("*").eq("email", user_email).single().execute()
    user_profile = profile_data.data
    
    # If the user completed Stripe but the webhook is delayed by a few milliseconds
    if not user_profile:
        st.warning("🔄 Finalizing your secure workspace setup... Give us one moment.")
        st.button("Click to Refresh")
        st.stop()
        
    tier = user_profile["subscription_tier"]
    used = user_profile["generations_used"]
except Exception as e:
    st.error(f"Account syncing problem: {e}")
    st.stop()

limit = TIER_LIMITS.get(tier, 3)

# App Sidebar Setup
st.sidebar.header("🔐 Secure Workspace")
st.sidebar.write(f"Active User: `{user_email}`")
st.sidebar.markdown(f"Plan Tier: **{tier.upper()}**")
st.sidebar.progress(used / limit if limit > 0 else 0)
st.sidebar.write(f"Usage: {used} / {limit} runs used.")

if st.sidebar.button("Log Out / Exit"):
    st.session_state["user_email"] = None
    st.query_params.clear()
    st.rerun()

# Gatekeeper: Out of credits logic
if used >= limit:
    st.error(f"🚨 **Monthly limit reached for your {tier.capitalize()} account status.**")
    with st.container(border=True):
        st.markdown("### 💎 Replenish Generation Credits Instantly")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Basic Agent Suite**\n\n30 generations/mo\n\n**$29/mo**")
            st.link_button("Activate Basic Upgrade", f"https://stripe.com{user_email}")
        with c2:
            st.markdown("**Power Broker Suite ⭐**\n\n150 generations/mo\n\n**$59/mo**")
            st.link_button("Activate Pro Upgrade", f"https://stripe.com{user_email}", type="primary")
    st.stop()

# Actual Tool Interface
st.title("🚀 Your Campaign Suite Generator")
raw_description = st.text_area("Paste MLS data, notes, or raw property layout characteristics:", height=150)
tone = st.selectbox("Aesthetic Copy Tone", ["Luxury & Prestigious", "Warm & Inviting", "Modern & Punchy"])

if st.button("Generate Complete 7-Part Suite ✨", type="primary"):
    if not raw_description.strip():
        st.error("Please insert property specifications first.")
    else:
        with st.spinner("Writing text structures..."):
            try:
                system_prompt = f"You are a real estate marketer. Build a 7-part comprehensive marketing campaign matrix in a {tone} tone using clear headers."
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": raw_description}]
                )
                
                # Update usage database entry
                supabase.table("profiles").update({"generations_used": used + 1}).eq("email", user_email).execute()
                
                st.success("Campaign Ready!")
                st.markdown(response.choices[0].message.content)
                st.button("Acknowledge & Refresh View")
            except Exception as e:
                st.error(f"Generation failure: {e}")




