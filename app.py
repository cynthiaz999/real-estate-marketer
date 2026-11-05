import streamlit as st
from openai import OpenAI

# 1. Page Configuration
st.set_page_config(page_title="Instant Real Estate Copywriter", page_icon="🏠", layout="centered")

st.title("🏠 Real Estate Copy Generator")
st.write("Turn raw property notes into a complete marketing suite instantly.")

# 2. Secure Hidden API Key Management
# This looks for the OPENAI_API_KEY you saved in your Streamlit Secrets setting
try:
    openai_api_key = st.secrets["OPENAI_API_KEY"]
    client = OpenAI(api_key=openai_api_key)
except Exception:
    st.error("Setup Error: Please add your OPENAI_API_KEY to your Streamlit App Secrets.")
    st.stop()

# 3. User Input Section
st.subheader("Property Details")
raw_description = st.text_area(
    "Paste your raw property notes, bullet points, or MLS data here:",
    height=200,
    placeholder="Example: 3 bed, 2.5 bath in North Austin. Built 2018. Quartz countertops, huge backyard, cul-de-sac. Walkable to coffee shop..."
)

# Optional style toggle
tone = st.selectbox("Select Marketing Tone", ["Enthusiastic & Luxury", "Casual & Warm", "Professional & Urgent"])

# 4. The Magic Prompt & Generation Logic
if st.button("Generate Marketing Suite ✨", type="primary"):
    if not raw_description.strip():
        st.error("Please provide some property details first.")
    else:
        # A highly structured system prompt ensures predictable, high-quality outputs
        system_prompt = (
            "You are an expert real estate copywriter. Your job is to take raw property information "
            "and convert it into highly compelling marketing materials. Maintain a tone that is "
            f"{tone}. Structure your output strictly with clear markdown headers for each requested piece."
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
                # Call the OpenAI API using a fast, cost-effective model
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.7
                )
                
                # Display Output
                st.success("Generation Complete!")
                st.divider()
                
                # Render the markdown output directly to the UI
                st.markdown(response.choices[0].message.content)
                
            except Exception as e:
                st.error(f"An error occurred: {e}")
