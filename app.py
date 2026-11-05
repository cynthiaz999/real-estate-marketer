import streamlit as st
from openai import OpenAI

# 1. Page Configuration & Custom Theme/CSS Override
st.set_page_config(page_title="PropCopy AI | Luxury Real Estate Copywriter", page_icon="🏠", layout="centered")

st.markdown("""
    <style>
    /* Styling the main container */
    .main .block-container {
        padding-top: 2rem;
        max-width: 750px;
    }
    /* Sleek primary button styling */
    div.stButton > button:first-child {
        background-color: #1E3A8A;
        color: white;
        font-weight: 600;
        border-radius: 8px;
        width: 100%;
        padding: 0.6rem;
        border: none;
        transition: background-color 0.3s;
    }
    div.stButton > button:first-child:hover {
        background-color: #3B82F6;
        color: white;
    }
    /* Card-like borders for results */
    .result-box {
        background-color: #f8fafc;
        padding: 20px;
        border-radius: 10px;
        border: 1px solid #e2e8f0;
        margin-bottom: 20px;
    }
    </style>
""", unsafe_allow_html=True)

# App Header
st.markdown("<h1 style='text-align: center; color: #1E3A8A; margin-bottom: 5px;'>PropCopy AI</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #64748B; font-size: 1.1rem; margin-bottom: 30px;'>Instantly turn raw property specs into an elite marketing suite.</p>", unsafe_allow_html=True)

# 2. Secure Hidden API Key Management
try:
    openai_api_key = st.secrets["OPENAI_API_KEY"]
    client = OpenAI(api_key=openai_api_key)
except Exception:
    st.error("Setup Error: Please add your OPENAI_API_KEY to your Streamlit App Secrets.")
    st.stop()

# 3. User Input Layout
with st.container():
    raw_description = st.text_area(
        "✨ Property Notes & Specs",
        height=180,
        placeholder="Type or paste your raw notes here (e.g., 5,800 sqft, infinity pool, quartz counters, walkable neighborhood...)"
    )
    
    col1, col2 = st.columns([2, 1])
    with col1:
        tone = st.selectbox("🎯 Brand Voice / Tone", ["Enthusiastic & Luxury", "Casual & Warm", "Professional & Urgent", "Story-driven Storyteller"])
    with col2:
        st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
        generate_btn = st.button("Generate Campaign ✨")

# 4. Processing & Displaying Outputs cleanly in Tabs
if generate_btn:
    if not raw_description.strip():
        st.error("Please provide some property details first.")
    else:
        system_prompt = (
            "You are an elite, highly paid real estate copywriter. Your job is to turn raw property info "
            f"into captivating marketing materials. Tone: {tone}. For each piece, generate highly descriptive "
            "copy optimized for conversion. Do not include markdown headers inside the text blocks, just output the clean text directly."
        )
        
        # We query the AI to separate fields cleanly using unique splitters
        user_prompt = f"""
        Analyze these property notes and generate 4 specific fields. Separate each field with exactly this text marker: '===SPLIT==='
        
        Field 1 (Social Media Bundle): Generate 3 distinct social posts. Post 1 for Instagram (visual, emojis, heavy hashtags, CTA to DM). Post 2 for Facebook (lifestyle focus, family-friendly, neighborly). Post 3 for LinkedIn (investment angle, architecture metrics).
        Field 2 (Video Script): A short, punchy 30-second TikTok/Reels script with visual cues [Bracketed] and voiceover narration.
        Field 3 (Email Blast): A complete email newsletter framework with an irresistible subject line, elegant body text expanding on specs, and an Open House call-to-action placeholder.
        Field 4 (Flyer Copy): A bold luxury headline, short summary paragraph, bulleted features list, and a contact placeholder.

        ---
        PROPERTY NOTES:
        {raw_description}
        """

        with st.spinner("Our AI copywriter is crafting your campaign..."):
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.7
                )
                
                output_text = response.choices[0].message.content
                parts = output_text.split("===SPLIT===")
                
                # Fallback to make sure parsing works safely
                social_copy = parts[0] if len(parts) > 0 else "Error generating copy."
                video_copy = parts[1] if len(parts) > 1 else "Error generating script."
                email_copy = parts[2] if len(parts) > 2 else "Error generating email."
                flyer_copy = parts[3] if len(parts) > 3 else "Error generating flyer."

                st.success("Campaign Ready!")
                st.divider()
                
                # Render beautifully inside visual tabs
                tab1, tab2, tab3, tab4 = st.tabs(["📱 Social Bundle", "🎥 Video Scripts", "✉️ Email Blast", "📄 Print Flyer"])
                
                with tab1:
                    st.caption("Copy and paste these directly to Instagram, Facebook, and LinkedIn:")
                    st.text_area("Social Posts", value=social_copy.strip(), height=350)
                    
                with tab2:
                    st.caption("Short-form video storyboard:")
                    st.text_area("TikTok / Reels Script", value=video_copy.strip(), height=300)
                    
                with tab3:
                    st.caption("Ready-to-send newsletter copy:")
                    st.text_area("Email Newsletter", value=email_copy.strip(), height=350)
                    
                with tab4:
                    st.caption("Clean text layout for your physical or digital flyers:")
                    st.text_area("Flyer Layout Copy", value=flyer_copy.strip(), height=300)
                
            except Exception as e:
                st.error(f"An error occurred: {e}")

