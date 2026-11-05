import streamlit as st
from openai import OpenAI

# 1. Elegant Page Configuration
st.set_page_config(page_title="PropCopy AI | Real Estate Copywriter", page_icon="🏠", layout="centered")

# Custom CSS for a professional, premium look
st.markdown("""
    <style>
    /* Clean up top padding */
    .main .block-container {
        padding-top: 3rem;
        max-width: 750px;
    }
    /* Premium dark blue button styling */
    div.stButton > button:first-child {
        background-color: #1E3A8A;
        color: white;
        font-weight: 600;
        border-radius: 8px;
        width: 100%;
        padding: 0.7rem;
        border: none;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    div.stButton > button:first-child:hover {
        background-color: #2563EB;
        color: white;
    }
    </style>
""", unsafe_allow_html=True)

# App Branding Headers
st.markdown("<h1 style='text-align: center; color: #1E3A8A; font-family: sans-serif; margin-bottom: 0px;'>PropCopy AI</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #64748B; font-size: 1.1rem; margin-bottom: 30px;'>Instantly turn raw property specs into an elite marketing suite.</p>", unsafe_allow_html=True)

# 2. Secure Hidden API Key Management
try:
    openai_api_key = st.secrets["OPENAI_API_KEY"]
    client = OpenAI(api_key=openai_api_key)
except Exception:
    st.error("Setup Error: Please add your OPENAI_API_KEY to your Streamlit App Secrets.")
    st.stop()

# 3. User Input Layout
st.subheader("🏠 Property Details")
raw_description = st.text_area(
    "Paste your raw property notes, bullet points, or MLS data here:",
    height=200,
    placeholder="Example: 3 bed, 2.5 bath in North Austin. Built 2018. Quartz countertops, huge backyard, cul-de-sac. Needs minor carpet replacement in master bedroom. Walkable to coffee shop..."
)

tone = st.selectbox("🎯 Brand Voice / Tone", ["Enthusiastic & Luxury", "Casual & Warm", "Professional & Urgent"])

# 4. Optimized Generation Logic
if st.button("Generate Complete Marketing Suite ✨", type="primary"):
    if not raw_description.strip():
        st.error("Please provide some property details first.")
    else:
        system_prompt = (
            "You are an expert real estate copywriter. Your job is to take raw property information "
            "and convert it into highly compelling, deeply descriptive marketing materials. Maintain a tone that is "
            f"{tone}. Structure your output strictly with clear markdown headers for each requested piece."
        )
        
        # Enhanced prompt instructions explicitly forcing the AI to write long, detailed posts
        user_prompt = f"""
        Analyze these property notes and generate the following items. Make sure each section is highly comprehensive, detailed, and completely written out:
        
        1. ## 📱 Post 1: Instagram (The Hook)
        Write a long, highly descriptive caption. Paint a vivid picture of the home's atmosphere. Use heavy, relevant emojis throughout. Include a strong Call to Action (CTA) telling users to DM for private viewings, followed by a dedicated block of highly relevant real estate hashtags.

        2. ## 👥 Post 2: Facebook (The Lifestyle Story)
        Write an exhaustive, longer-form narrative post focusing heavily on the lifestyle, the neighborhood vibe, and community benefits (family-friendly features, walkability, or entertaining potential). Include a warm, engaging CTA.

        3. ## 💼 Post 3: LinkedIn (The Property Investment)
        Write a professional, long-form post highlighting the structural metrics, premium architectural choices, market value retention indicators, or upscale investment potential. Use professional real estate terminology.

        4. ## 🎥 Post 4: Short-Form Video Script (TikTok/Reels)
        Provide an engaging 30-second video storyboard. Clearly detail what visual transitions to show on screen inside [brackets] and include a punchy, enthusiastic voiceover script to read out loud.

        5. ## 📋 Post 5: Just Listed Fast Summary
        A fast, highly scannable, multi-bulleted list outlining the property’s premium specs for quick reading.

        6. ## ✉️ Email Newsletter Blast
        Provide a complete email marketing layout. Include an irresistible Subject Line, a warm introductory greeting, a descriptive multi-paragraph body expanding on the property benefits, an Open House scheduling placeholder, and a clear CTA button line.

        7. ## 📄 Print Flyer Layout Copy
        A bold, luxury-style headline, a beautifully summarized property paragraph, bulleted specs, and a placeholder for Realtor Contact details.

        ---
        PROPERTY NOTES:
        {raw_description}
        """

        with st.spinner("AI is crafting your complete campaign..."):
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.7
                )
                
                st.success("Generation Complete!")
                st.divider()
                
                # Render the clean, long markdown document directly to the screen like the original version
                st.markdown(response.choices.message.content)
                
            except Exception as e:
                st.error(f"An error occurred: {e}")


